/**
 * DeckAI Cockpit v2 — Stream Dock Plugin
 * Uses the REAL $SD SDK from plugin.js
 */

// ---- DEBUG: phone-home pings visible in cockpit uvicorn log ----
function _ping(tag) {
    new Image().src = "http://127.0.0.1:8000/state?_deckai=" + tag + "&t=" + Date.now();
}
_ping("index_loaded");

// ---- Python Cockpit WebSocket -----------------------------------
var cockpitWs = null;
var cockpitImages = {};

function connectCockpit() {
    _ping("connectCockpit");
    if (cockpitWs && cockpitWs.readyState === WebSocket.OPEN) return;
    try {
        cockpitWs = new WebSocket("ws://127.0.0.1:8000/ws");
    } catch (e) {
        setTimeout(connectCockpit, 2000);
        return;
    }
    cockpitWs.onopen = function () {
        _ping("cockpit_ws_open");
    };
    cockpitWs.onmessage = function (e) {
        _ping("cockpit_ws_msg");
        try {
            var state = JSON.parse(e.data);
            for (var key in state.buttons) {
                if (state.buttons.hasOwnProperty(key)) {
                    cockpitImages[key] = state.buttons[key];
                }
            }
            updateTrafficLight(state.traffic_light);
            updateDisplays(state);
        } catch (err) {
            console.warn("[DeckAI] WS parse:", err);
        }
    };
    cockpitWs.onclose = function () {
        cockpitWs = null;
        setTimeout(connectCockpit, 2000);
    };
}


// ---- Button contexts --------------------------------------------
var trafficBtnCtx = {};
var modeBtnCtx = {};
var vscodeCtx = null;


// ---- Update functions -------------------------------------------
function updateTrafficLight(active) {
    var colors = ["green", "yellow", "red"];
    for (var i = 0; i < colors.length; i++) {
        var c = colors[i];
        var ctx = trafficBtnCtx[c];
        if (!ctx) continue;
        var key = "btn_traffic_" + c;
        var base64 = cockpitImages[key];
        if (base64) {
            $SD.setImage(ctx, "data:image/png;base64," + base64);
        }
        var label = c === "green" ? "BEREIT" : c === "yellow" ? "ARBEITET" : "FEHLER";
        var mark = active === c ? " *" : "";
        $SD.setTitle(ctx, label + mark);
    }
}

function updateDisplays(state) {
    var ectx = modeBtnCtx["effort"];
    if (ectx) {
        var ekey = "btn_effort";
        if (cockpitImages[ekey]) {
            $SD.setImage(ectx, "data:image/png;base64," + cockpitImages[ekey]);
        }
        $SD.setTitle(ectx, state.effort || "Medium");
    }
    var mctx = modeBtnCtx["mode"];
    if (mctx) {
        var mkey = "btn_mode";
        if (cockpitImages[mkey]) {
            $SD.setImage(mctx, "data:image/png;base64," + cockpitImages[mkey]);
        }
        $SD.setTitle(mctx, state.mode || "Agent");
    }
}


// ---- wsReady helper — defer $SD calls until websocket open ------
var wsReady = false;
var pendingUpdates = [];

function flushPending() {
    while (pendingUpdates.length > 0) {
        pendingUpdates.shift()();
    }
}

function whenReady(fn) {
    if (wsReady) { fn(); }
    else { pendingUpdates.push(fn); }
}


// ---- Action handlers (routed by websocket.onmessage) -----------
var $data = {
    "com.deckai.traffic": {
        willAppear: function (data) {
            _ping("traffic_willAppear");
            var ctx = data.context;
            var settings = (data.payload && data.payload.settings) || {};
            var role = settings.role || "traffic_green";
            var color = role.split("_")[1];
            trafficBtnCtx[color] = ctx;

            var key = "btn_" + role;
            whenReady(function () {
                var base64 = cockpitImages[key];
                if (base64) {
                    $SD.setImage(ctx, "data:image/png;base64," + base64);
                } else {
                    $SD.setImage(ctx, "http://127.0.0.1:8000/static/" + key + ".png");
                }
                $SD.setTitle(ctx, color.toUpperCase());
                $SD.setSettings(ctx, { role: role });
            });
        },
        willDisappear: function (data) {
            for (var r in trafficBtnCtx) {
                if (trafficBtnCtx[r] === data.context) delete trafficBtnCtx[r];
            }
        },
        keyDown: function () {
            var xhr = new XMLHttpRequest();
            xhr.open("GET", "http://127.0.0.1:8000/state", true);
            xhr.send();
        }
    },

    "com.deckai.display": {
        willAppear: function (data) {
            var ctx = data.context;
            var settings = (data.payload && data.payload.settings) || {};
            var role = settings.role || "effort";
            modeBtnCtx[role] = ctx;

            var key = role === "effort" ? "btn_effort" : "btn_mode";
            whenReady(function () {
                var base64 = cockpitImages[key];
                if (base64) {
                    $SD.setImage(ctx, "data:image/png;base64," + base64);
                } else {
                    $SD.setImage(ctx, "http://127.0.0.1:8000/static/" + key + ".png");
                }
                $SD.setTitle(ctx, role === "effort" ? "Medium" : "Agent");
                $SD.setSettings(ctx, { role: role });
            });
        },
        willDisappear: function (data) {
            for (var r in modeBtnCtx) {
                if (modeBtnCtx[r] === data.context) delete modeBtnCtx[r];
            }
        }
    },

    "com.deckai.vscode": {
        willAppear: function (data) {
            vscodeCtx = data.context;
            whenReady(function () {
                var base64 = cockpitImages["btn_vscode"];
                if (base64) {
                    $SD.setImage(vscodeCtx, "data:image/png;base64," + base64);
                } else {
                    $SD.setImage(vscodeCtx, "http://127.0.0.1:8000/static/vscode_focus.png");
                }
                $SD.setTitle(vscodeCtx, "VS CODE");
            });
        },
        willDisappear: function () {
            vscodeCtx = null;
        },
        keyDown: function () {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "http://127.0.0.1:8000/focus/vscode", true);
            xhr.send();
        }
    }
};


// ---- Plugin registration (called by VSD Craft host) -------------
function connectElgatoStreamDeckSocket(inPort, inPluginUUID, inRegisterEvent, inInfo) {
    _ping("elgato_connect_port" + inPort);
    websocket = new WebSocket("ws://127.0.0.1:" + inPort);

    websocket.onopen = function () {
        _ping("elgato_ws_open");
        wsReady = true;
        websocket.send(JSON.stringify({ event: inRegisterEvent, uuid: inPluginUUID }));
        flushPending();
    };

    websocket.onmessage = function (e) {
        var data = JSON.parse(e.data);
        if (data.action && $data[data.action]) {
            var handler = $data[data.action][data.event];
            if (typeof handler === "function") handler(data);
        }
        if ($data[data.event]) {
            $data[data.event](data);
        }
    };
}

// ---- Start ------------------------------------------------------
connectCockpit();
console.log("[DeckAI v2] Plugin ready");
