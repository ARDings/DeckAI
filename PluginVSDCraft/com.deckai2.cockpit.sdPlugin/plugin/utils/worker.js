// Timer Web Worker for Stream Dock plugin SDK
const timers = { setTimeout: {}, setInterval: {} };
let idCounter = 0;

self.onmessage = function (e) {
    const { event, id, delay } = e.data;

    if (event === 'setTimeout') {
        const tid = id || ++idCounter;
        timers.setTimeout[tid] = setTimeout(() => {
            self.postMessage({ event: 'setTimeout', id: tid });
            delete timers.setTimeout[tid];
        }, delay);
    } else if (event === 'setInterval') {
        const tid = id || ++idCounter;
        timers.setInterval[tid] = setInterval(() => {
            self.postMessage({ event: 'setInterval', id: tid });
        }, delay);
    } else if (event === 'clearTimeout') {
        if (timers.setTimeout[id]) {
            clearTimeout(timers.setTimeout[id]);
            delete timers.setTimeout[id];
        }
    } else if (event === 'clearInterval') {
        if (timers.setInterval[id]) {
            clearInterval(timers.setInterval[id]);
            delete timers.setInterval[id];
        }
    }
};
