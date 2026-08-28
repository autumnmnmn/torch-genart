export async function main() {
    const topmost = $div("pyt-debug");

    const output = $div("pyt-debug-output");
    const input = $element("input");
    input.type = "text";
    input.placeholder = "message";
    const sendButton = $element("button");
    sendButton.innerText = "send";

    const controls = $div("pyt-debug-controls").$with(input, sendButton);
    topmost.$with(output, controls);

    const ws = new WebSocket("ws://" + location.hostname + ":1314");
    ws.binaryType = "arraybuffer";

    const append = (text) => {
        const line = $element("pre");
        line.innerText = text;
        output.$with(line);
    };

    ws.onmessage = (event) => {
        if (typeof event.data === "string") {
            append(event.data);
        } else {
            append("[binary: " + event.data.byteLength + " bytes]");
        }
    };

    ws.onopen = () => append("[connected]");
    ws.onclose = () => append("[disconnected]");
    ws.onerror = (e) => console.log(e);

    const send = () => {
        if (ws.readyState !== WebSocket.OPEN) return;
        ws.send(input.value);
        input.value = "";
    };

    sendButton.addEventListener("click", send);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") send();
    });

    function exitTool() {
        ws.close();
        const parent = topmost.parentNode;
        topmost.remove();
        $apply("layout/nothing", parent);
    }

    topmost.$contextMenu = {
        items: [
            ["exit", exitTool]
        ]
    };

    input.focus();

    return {
        dom: [topmost],
        replace: true
    };
}
