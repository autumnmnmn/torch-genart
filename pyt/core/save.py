
# Vibecoded - GLM 5.2

import asyncio
import threading
import queue
import websockets
import json
import io
import os
# TODO check if torch is available and only include tensor handling in that case
# if torch is available but safetensors isn't just complain loudly to stderr & fail to save i guess
import torch
from safetensors.torch import save as safe_save

# Shared queue holds tuples of (metadata_dict, raw_bytes_or_None)
ws_send_queue = queue.Queue()
ws_server_running = False

def is_image_like(tensor):
    if tensor.ndim == 2:
        return True
    if tensor.ndim == 3 and tensor.shape[0] in (1, 3, 4):
        return True
    return False

def live_save(obj, name="output", to_disk=False, disk_path="out/"):
    """Figures out how to handle arbitrary objects, streaming to UI and/or disk."""
    
    # 1. Handle Tensors
    if isinstance(obj, torch.Tensor):
        tensor = obj.detach().cpu()
        
        # Safetensors can't save bfloat16 directly to bytes, cast to float32 just in case
        if tensor.dtype == torch.bfloat16:
            tensor = tensor.to(torch.float32)
            
        # Disk saving logic
        if to_disk:
            os.makedirs(disk_path, exist_ok=True)
            if is_image_like(tensor):
                from pyt.lib.util import pilify, mpilify
                img = mpilify(tensor) if tensor.ndim == 2 else pilify(tensor)
                img.save(f"{disk_path}/{name}.png")
            else:
                # Save arbitrary shapes as safetensors
                buffer = io.BytesIO()
                safe_save({"tensor": tensor.contiguous()}, buffer)
                with open(f"{disk_path}/{name}.safetensors", "wb") as f:
                    f.write(buffer.getvalue())

        # WebSocket streaming logic
        if is_image_like(tensor):
            # Raw bytes for image-like data (UI will reconstruct)
            metadata = {
                "type": "tensor_image",
                "name": name,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype).replace("torch.", "")
            }
            raw_bytes = tensor.contiguous().numpy().tobytes()
            ws_send_queue.put((metadata, raw_bytes))
        else:
            # Raw bytes for arbitrary tensors as safetensors
            buffer = io.BytesIO()
            safe_save({"tensor": tensor.contiguous()}, buffer)
            metadata = {
                "type": "safetensors",
                "name": name,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype).replace("torch.", "")
            }
            ws_send_queue.put((metadata, buffer.getvalue()))
            
    # 2. Handle Text/JSON
    elif isinstance(obj, (str, dict, list, int, float)):
        metadata = {
            "type": "text",
            "name": name,
            "data": json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj
        }
        ws_send_queue.put((metadata, None))
        
    # 3. Fallback
    else:
        ws_send_queue.put(({"type": "text", "name": name, "data": repr(obj)}, None))


# --- WebSocket Server ---
async def handler(websocket):
    print("WebUI connected!")
    try:
        while True:
            # Wait for data from main thread without blocking event loop
            metadata, raw_bytes = await asyncio.to_thread(ws_send_queue.get)
            if metadata is None: 
                break
            
            # 1. Send JSON metadata as a text frame
            await websocket.send(json.dumps(metadata))
            
            # 2. If there's binary data, send it as a binary frame immediately after
            if raw_bytes is not None:
                await websocket.send(raw_bytes)
                
    except websockets.exceptions.ConnectionClosed:
        pass

async def run_server():
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()  # Run forever

def start_server_thread():
    global ws_server_running
    if not ws_server_running:
        threading.Thread(target=asyncio.run, args=(run_server(),), daemon=True).start()
        ws_server_running = True




""" suggested client code:

export async function main(target) {
    const container = $div("live-sink-container");
    target.$with(container);

    const ws = new WebSocket("ws://localhost:8765");
    ws.binaryType = "arraybuffer"; // Tell JS we expect raw binary

    let pendingMeta = null;

    ws.onmessage = (event) => {
        // 1. Handle Text Frame (JSON Metadata)
        if (typeof event.data === "string") {
            const meta = JSON.parse(event.data);
            
            // If it's just text, render it immediately
            if (meta.type === "text") {
                renderText(meta);
            } 
            // Otherwise, store metadata and wait for the binary frame
            else {
                pendingMeta = meta;
            }
        } 
        // 2. Handle Binary Frame (Raw Bytes)
        else if (event.data instanceof ArrayBuffer) {
            if (pendingMeta) {
                if (pendingMeta.type === "tensor_image") {
                    renderRawTensor(pendingMeta, event.data);
                } else if (pendingMeta.type === "safetensors") {
                    renderSafetensorsMeta(pendingMeta, event.data);
                }
                pendingMeta = null;
            }
        }
    };

    function renderRawTensor(meta, buffer) {
        const item = $div("live-sink-item");
        const title = $div();
        title.innerText = `${meta.name} (${meta.shape.join("x")})`;
        title.style.marginBottom = "0.5rem";
        item.$with(title);

        const canvas = $element("canvas");
        const ctx = canvas.getContext("2d");

        // Reconstruct shape
        const [c, h, w] = (meta.shape.length === 3) ? meta.shape : [1, ...meta.shape];
        canvas.width = w;
        canvas.height = h;

        // Create ImageData to draw on canvas
        const imageData = ctx.createImageData(w, h);
        const pixels = imageData.data; // Uint8ClampedArray (RGBA)

        const bytes = new Uint8Array(buffer);

        // Fast mapping of tensor data to RGBA
        if (c === 1) {
            // Monochrome [H, W] or [1, H, W]
            for (let i = 0; i < w * h; i++) {
                const val = bytes[i]; // Assuming uint8 for now, adjust if float32
                pixels[i * 4] = val;
                pixels[i * 4 + 1] = val;
                pixels[i * 4 + 2] = val;
                pixels[i * 4 + 3] = 255;
            }
        } else if (c === 3) {
            // RGB [3, H, W]
            const stride = h * w;
            for (let i = 0; i < stride; i++) {
                pixels[i * 4] = bytes[i];               // R
                pixels[i * 4 + 1] = bytes[i + stride];  // G
                pixels[i * 4 + 2] = bytes[i + stride*2];// B
                pixels[i * 4 + 3] = 255;                // A
            }
        }

        ctx.putImageData(imageData, 0, 0);
        item.$with(canvas);
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }

    function renderSafetensorsMeta(meta, buffer) {
        const item = $div("live-sink-item");
        const title = $div();
        title.innerText = `${meta.name} (Safetensors)`;
        title.style.marginBottom = "0.5rem";
        item.$with(title);

        const pre = $element("pre");
        // Just show the shape/dtype, don't try to parse the whole safetensors binary in JS
        pre.innerText = `Shape: ${meta.shape.join("x")}\nDType: ${meta.dtype}\nSize: ${buffer.byteLength} bytes`;
        item.$with(pre);
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }

    function renderText(meta) {
        const item = $div("live-sink-item");
        const pre = $element("pre");
        pre.innerText = meta.data;
        item.$with(pre);
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }

    ws.onclose = () => {
        const err = $div();
        err.innerText = "Connection to snakepyt lost.";
        err.style.color = "red";
        container.prepend(err);
    };

    return { replace: true };
}

"""

