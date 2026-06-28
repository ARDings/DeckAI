/**
 * Stream Dock Plugin SDK — minimal bundled utilities.
 * Provides: Plugins, Actions, WebSocket connection, setImage/setTitle/...
 *
 * Based on the MiraboxSpace StreamDock-Plugin-SDK (MIT-licensed template).
 */

// ---- Timer worker ------------------------------------------------
const Timer = new Worker('./utils/worker.js');
const TimerSubscribe = { setTimeout: {}, setInterval: {} };

Timer.onmessage = function (e) {
    const cb = TimerSubscribe[e.data.event]?.[e.data.id];
    if (typeof cb === 'function') cb();
};

// ---- Actions class -----------------------------------------------
function Actions(data) {
    this.data = {};
    this.default = {};
    Object.assign(this, data);
}

Actions.currentAction = null;
Actions.currentContext = null;

Actions.prototype.propertyInspectorDidAppear = function (d) {
    Actions.currentAction = d.action;
    Actions.currentContext = d.context;
    if (this._propertyInspectorDidAppear) this._propertyInspectorDidAppear(d);
};

Actions.prototype.willAppear = function (d) {
    var ctx = d.context;
    var settings = (d.payload && d.payload.settings) || {};
    this.data[ctx] = Object.assign({}, this.default, settings);
    if (this._willAppear) this._willAppear(d);
};

Actions.prototype.willDisappear = function (d) {
    if (this._willDisappear) this._willDisappear(d);
    delete this.data[d.context];
};

// ---- Plugins class ----------------------------------------------
function Plugins(name) {
    this.name = name;
}

Plugins.prototype.clearTimeout = function (id) {
    Timer.postMessage({ event: 'clearTimeout', id: id });
};

Plugins.prototype.setTimeout = function (id, callback, delay) {
    this.clearTimeout(id);
    TimerSubscribe.setTimeout[id] = callback;
    Timer.postMessage({ event: 'setTimeout', id: id, delay: delay });
};

Plugins.prototype.clearInterval = function (id) {
    Timer.postMessage({ event: 'clearInterval', id: id });
};

Plugins.prototype.setInterval = function (id, callback, delay) {
    this.clearInterval(id);
    TimerSubscribe.setInterval[id] = callback;
    Timer.postMessage({ event: 'setInterval', id: id, delay: delay });
};

// ---- WebSocket entry point (called by Stream Dock host) ---------
window.connectElgatoStreamDeckSocket = function () {
    var port = arguments[0];
    var uuid = arguments[1];
    var event = arguments[2];
    var info  = JSON.parse(arguments[3]);

    window.info = info;
    window.socket = new WebSocket('ws://127.0.0.1:' + port);

    // ---- Prototype extensions ----

    WebSocket.prototype.openUrl = function (url) {
        this.send(JSON.stringify({ event: 'openUrl', payload: { url: url } }));
    };

    WebSocket.prototype.sendToPropertyInspector = function (payload) {
        this.send(JSON.stringify({
            event: 'sendToPropertyInspector',
            action: Actions.currentAction,
            context: Actions.currentContext,
            payload: payload
        }));
    };

    WebSocket.prototype.setSettings = function (context, payload) {
        this.send(JSON.stringify({ event: 'setSettings', context: context, payload: payload }));
    };

    WebSocket.prototype.setImage = function (context, url) {
        var img = new Image();
        img.src = url;
        img.onload = function () {
            var canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            var dataUrl = canvas.toDataURL('image/png');
            window.socket.send(JSON.stringify({
                event: 'setImage',
                context: context,
                payload: {
                    image: dataUrl,
                    target: 0
                }
            }));
        };
        img.onerror = function () {
            console.warn('[DeckAI] Failed to load image: ' + url.substring(0, 50) + '...');
        };
    };

    WebSocket.prototype.setTitle = function (context, str, row, num) {
        row = row || 0;
        num = num || 6;
        var title = str;
        if (row > 0) {
            var result = '';
            for (var i = 0; i < row && i * num < str.length; i++) {
                result += str.substring(i * num, (i + 1) * num);
                if (i < row - 1 && (i + 1) * num < str.length) result += '\n';
            }
            if (str.length > row * num) result = result.substring(0, result.length - 1) + '..';
            title = result;
        }
        this.send(JSON.stringify({
            event: 'setTitle',
            context: context,
            payload: { title: title, target: 0 }
        }));
    };

    WebSocket.prototype.setState = function (context, state) {
        this.send(JSON.stringify({
            event: 'setState',
            context: context,
            payload: { state: state }
        }));
    };

    // ---- Socket event handlers ----

    window.socket.onopen = function () {
        window.socket.send(JSON.stringify({
            event: event,
            uuid: uuid
        }));
    };

    window.socket.onmessage = function (msg) {
        var data = JSON.parse(msg.data);
        // Route to action-specific handler: plugin.<actionName>.<eventName>(data)
        var actionName = data.action ? data.action.split('.').pop() : null;
        if (actionName && window.plugin && window.plugin[actionName]) {
            var handler = window.plugin[actionName][data.event];
            if (typeof handler === 'function') handler(data);
        }
        // Fallback: plugin-wide handler
        if (window.plugin && typeof window.plugin[data.event] === 'function') {
            window.plugin[data.event](data);
        }
    };
};
