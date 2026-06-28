let websocket = null;
let DestinationEnum = Object.freeze({
    "HARDWARE_AND_SOFTWARE": 0, // 软硬件
    "HARDWARE_ONLY": 1, // 仅硬件
    "SOFTWARE_ONLY": 2 // 仅软件
})

/* 插件通信 */
const $SD = {
    /* 设置标题 */
    setTitle(context, title) {
        websocket.send(JSON.stringify({
            "event": "setTitle",
            "context": context,
            "payload": {
                "title": "" + title,
                "target": DestinationEnum.HARDWARE_AND_SOFTWARE
            }
        }))
    },
    /* 设置存储 */
    setSettings(context, payload) {
        websocket.send(JSON.stringify({
            "event": "setSettings",
            "context": context,
            "payload": payload
        }))
    },
    /* 打开网址 */
    openUrl(url) {
        websocket.send(JSON.stringify({
            "event": "openUrl",
            "payload": { url }
        }))
    },
    /* 发送给属性选择器 */
    sendToPropertyInspector(action, context, payload) {
        websocket.send(JSON.stringify({
            "event": "sendToPropertyInspector",
            "action": action,
            "context": context,
            "payload": payload
        }))
    },
    /* 设置背景图 */
    setImage(context, url) {
        let image = new Image();
        image.src = url;
        image.onload = function () {
            let canvas = document.createElement("canvas");
            canvas.width = this.naturalWidth;
            canvas.height = this.naturalHeight;
            let ctx = canvas.getContext("2d");
            ctx.drawImage(this, 0, 0);

            /* 发送请求 */
            websocket.send(JSON.stringify({
                "event": "setImage",
                "context": context,
                "payload": {
                    image: canvas.toDataURL("image/png") || "",
                    target: DestinationEnum.HARDWARE_AND_SOFTWARE
                }
            }))
        }
    },
    /* 绘制角标 默认右下角 */
    setJB(context, url, site = 3) {
        let image = new Image(); image.src = url;
        image.onload = function () {
            let canvas = document.createElement("canvas");
            canvas.width = canvas.height = 126;
            let ctx = canvas.getContext("2d");

            /* 动态绘制背景 */
            ctx.fillStyle = 'rgb(0,29,123)'
            ctx.fillRect(0, 0, 126, 126); ctx.save();

            /* 根据位置绘制图标 */
            let img = [40, 40] // 指定图片大小 w,h
            site === 0 && ctx.drawImage(this, 10, 10, ...img);
            site === 1 && ctx.drawImage(this, 86, 10, ...img);
            site === 2 && ctx.drawImage(this, 10, 86, ...img);
            site === 3 && ctx.drawImage(this, 86, 86, ...img);

            $SD.setImage(context, canvas.toDataURL("image/png"))
        }
    },
    /* 绘制背景色 */
    setBG(context, color) {
        let canvas = document.createElement("canvas");
        canvas.width = canvas.height = 126;
        let ctx = canvas.getContext("2d");

        /* 动态绘制背景色 */
        ctx.fillStyle = color
        ctx.fillRect(0, 0, 126, 126);
        $SD.setImage(context, canvas.toDataURL("image/png"))
    }
}

/* 工具库 */
const $ = (num) => num < 10 ? '0' + num : num;

/* 限制字符长度显示 */
$.split = (str, row) => {
    let nowRow = 1, newStr = '', strArr = str.split('')
    strArr.forEach((item, index) => {
        if (nowRow < row && index >= nowRow * 6) {
            nowRow++
            newStr += '\n'
        }
        if (nowRow <= row && index < nowRow * 6) {
            newStr += item
        }
    })
    if (strArr.length > row * 6) {
        newStr = newStr.substring(0, newStr.length - 1)
        newStr += '..'
    }
    return newStr;
}

/* 高精度定时器 */
class Timer {
    constructor(task, interval, immediate = false) {
        if (immediate) task() // 是否立刻执行一次
        this.worker = new Worker('../static/worker.js');
        this.worker.postMessage(interval);
        this.worker.onmessage = task;
    }
    /* 停止定时器 */
    stop() {
        this.worker.terminate();
    }
}