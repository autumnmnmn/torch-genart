
$css(`
    .lyapunov-webgpu.topmost {
        width: 100%;
        height: 100%;
        position: relative;
        display: flex;
        flex-direction: row;
    }

    .lyapunov-webgpu .overlay {
        user-select: none;
        position: absolute;
        z-index: 1;
        top: 0;
        left: 0;
        pointer-events: none;
    }

    .lyapunov-webgpu .color-detector {
        display: none;
        background-color: var(--main-background);
    }

    .lyapunov-webgpu .control-container {
        position: relative;
        width: fit-content;
        height: 100%;
        background-color: var(--faded-background);
        flex-shrink: 0;
    }

    @media (max-width: 768px) {
        .lyapunov-webgpu.topmost {
            flex-direction: column-reverse;
        }

        .lyapunov-webgpu.topmost > * {
            flex: 1 1 0;
        }

        .lyapunov-webgpu .control-container {
            flex-shrink: revert;
            width: 100%;
            height: fit-content;
        }
    }
`);

import { greek } from "/code/math/math.js";

import "/code/math/constants.js";
import { Vec2 as v2 } from "/code/math/vector.js";
import { cartesian as c } from "/code/math/complex.js";
import { splitDouble } from "/code/math/precision.js";

export async function main() {
    let canRender = false;

    const topmost = $div("lyapunov-webgpu topmost");

    const renderStack = $div("full");
    //let topmost = renderStack;
    renderStack.dataset.name = "renderer";
    renderStack.style.position = "relative";

    const canvasModule = await $apply("gpu/canvas", renderStack);

    const canvas = canvasModule.canvas;
    const context = canvasModule.context;

    canvas.setAttribute("aria-label",
        "Interactive visualization of a Lyapunov fractal.");
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-keyshortcuts", "f");

    const colorDetector = $div("color-detector");
    canvas.$with(colorDetector);

    const compShader = await $gpu.loadShader("lyapunov", {
        "pixel_mapping" : "pixel_to_complex"
    });
    const blitShader = await $gpu.loadShader("blit");

    if (!compShader || !blitShader) return;

    const uniforms = compShader.bufferDefinitions["0,0"];
    const params = uniforms.vars;

    const blitUniforms = blitShader.bufferDefinitions["0,0"];
    const blitParams = blitUniforms.vars;

    params.zoom = 0.25;


    var center_x = splitDouble(2.001);
    var center_y = splitDouble(-2.001);


    params.center_low_x = center_x[1];
    params.center_low_y = center_y[1];
    params.center_high_x = center_x[0];
    params.center_high_y = center_y[0];

    const controls = await $mod("control/panel",
        "Parameters", uniforms.getControlSettings(render).concat(blitUniforms.getControlSettings(render))
    );

    const computePipeline = $gpu.device.createComputePipeline({
        layout: "auto",
        compute: {
            module: compShader.module,
            entryPoint: "main"
        }
    });

    const renderPipeline = $gpu.device.createRenderPipeline({
        layout: "auto",
        vertex: {
            module: blitShader.module,
            entryPoint: "vert"
        },
        fragment: {
            module: blitShader.module,
            entryPoint: "frag",
            targets: [ { format: $gpu.canvasFormat } ]
        },
        primitive: {
            topology: "triangle-list"
        }
    });

    const overlay = $svgElement("svg");
    overlay.classList = "full overlay";

    overlay.setAttribute("aria-label",
        "Overlay visualizing the trajectory \
         starting from the point under the cursor.")

    renderStack.appendChild(overlay);

    const controlContainer = $div("control-container").$with(...controls.dom);
    controlContainer.style.display = "block";

    function setControlDisplayState(state) {
        const verb = state === "none" ? "hide" : "show";

        if (controlContainer.style.display === state) return;

        return [`${verb} controls`, async () => {
            controlContainer.style.display = state;
        }];
    }

    const observers = {};

    function parseRgb(rgbString) {
        const m = rgbString.match(/rgba?\(([^)]+)\)/);
        if (!m) return { r: 0, g: 0, b: 0, a: 1 };
        const [r, g, b, a = 1] = m[1].split(',').map(v => parseFloat(v) / 255);
        return { r, g, b, a };
    }

    let backgroundColor = { r: 0, g: 0, b: 0, a: 0 };

    const rgbaEq = (a, b) =>
        a.r === b.r &&
        a.g === b.g &&
        a.b === b.b &&
        a.a === b.a;

    const hue_neg = Math.floor(Math.random() * 360);
    const hue_pos = (hue_neg + 60) % 360;

    blitParams.neg_color = { space: "hsl", vals: [hue_neg, 80, 50] };
    blitParams.pos_color = { space: "hsl", vals: [hue_pos, 80, 50] };

    const retheme = () => {
        const style = getComputedStyle(colorDetector);
        const newBackgroundColor = parseRgb(style.backgroundColor);
        if (!rgbaEq(newBackgroundColor, backgroundColor)) {
            backgroundColor = newBackgroundColor;
            blitParams.nan_color = {
                space: "rgb",
                vals: [
                    backgroundColor.r * 255,
                    backgroundColor.g * 255,
                    backgroundColor.b * 255
                ]
            };
        }
    };

    observers.theme = new MutationObserver(() => {
        retheme();

        if (canRender) render();
    });
    observers.theme.observe(document.documentElement, {
        subtree: true,
        attributes: true,
        attributeFilter: ["data-theme"]
    });

    function exitRenderer() {
        observers.resize?.disconnect();
        observers.theme?.disconnect();
        if (document.fullscreenElement) {
            document.exitFullscreen();
        }
        const target = topmost.parentNode;
        target.replaceChildren();
        $apply("layout/nothing", target);
    }

    function saveFrame() {
        canvas.toBlob(blob => {
            const url = URL.createObjectURL(blob);
            const a = $element("a");
            a.href = url;
            a.download = `lyap_${Date.now()}.png`;
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    renderStack.$preventCollapse = true;

    renderStack.addEventListener("keydown", (e) => {
        if (e.key === "f") {
            if (document.fullscreenElement) {
                document.exitFullscreen();
            }
            else {
                topmost.requestFullscreen();
            }
        }
    });


    const dpr = window.devicePixelRatio || 1;
    let width = canvas.clientWidth * dpr;
    let height = canvas.clientHeight * dpr;

    let outputTexture;
    let computeBindGroup;
    let renderBindGroup;

    const sampler = $gpu.device.createSampler({ magFilter: "nearest", minFilter: "nearest" });


    async function offscreenRender(scalingFactor) {
        const dims = v2.of(width * scalingFactor, height * scalingFactor);

        const texture = $gpu.device.createTexture({
            size: [dims.x, dims.y],
            format: "rg32float",
            usage: GPUTextureUsage.STORAGE_BINDING | GPUTextureUsage.TEXTURE_BINDING,
        });

        const orig_height = params.height;
        const orig_width = params.width;

        params.height *= scalingFactor;
        params.width *= scalingFactor;

        computeBindGroup = $gpu.device.createBindGroup({
            layout: computePipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: uniforms.gpuBuffer } },
                { binding: 1, resource: texture.createView() }
            ]
        });

        renderBindGroup = $gpu.device.createBindGroup({
            layout: renderPipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: blitUniforms.gpuBuffer } },
                //{ binding: 0, resource: sampler },
                { binding: 1, resource: texture.createView() }
            ]
        });

        const offscreen = $gpu.getOffscreenContext(dims);

        render(offscreen.context, dims);

        params.height = orig_height;
        params.width = orig_width;

        const blob = await offscreen.canvas.convertToBlob({ type: "image/png" });

        const url = URL.createObjectURL(blob);
        const a = $element("a");
        a.href = url;
        a.download = `lyapunov_${Date.now()}.png`;
        a.click();
        URL.revokeObjectURL(url);
        texture.destroy();

        computeBindGroup = $gpu.device.createBindGroup({
            layout: computePipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: uniforms.gpuBuffer } },
                { binding: 1, resource: outputTexture.createView() }
            ]
        });

        renderBindGroup = $gpu.device.createBindGroup({
            layout: renderPipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: blitUniforms.gpuBuffer } },
                //{ binding: 0, resource: sampler },
                { binding: 1, resource: outputTexture.createView() }
            ]
        });

    }



    function resize() {
        width = canvas.clientWidth * dpr;
        height = canvas.clientHeight * dpr;

        overlay.setAttribute("viewBox", `0 0 ${width} ${height}`);
        overlay.setAttribute("width", width);
        overlay.setAttribute("height", height);

        retheme();

        canvas.width = width;
        canvas.height = height;

        const uniforms = compShader.bufferDefinitions["0,0"];

        params.width = width;
        params.height = height;

        if (width * height <= 0) {
            canRender = false;
            return;
        }

        canRender = true;

        outputTexture?.destroy();

        outputTexture = $gpu.device.createTexture({
            size: [width, height],
            format: "rg32float",
            usage: GPUTextureUsage.STORAGE_BINDING | GPUTextureUsage.TEXTURE_BINDING,
        });

        computeBindGroup = $gpu.device.createBindGroup({
            layout: computePipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: uniforms.gpuBuffer } },
                { binding: 1, resource: outputTexture.createView() }
            ]
        });

        renderBindGroup = $gpu.device.createBindGroup({
            layout: renderPipeline.getBindGroupLayout(0),
            entries: [
                { binding: 0, resource: { buffer: blitUniforms.gpuBuffer } },
                //{ binding: 0, resource: sampler },
                { binding: 1, resource: outputTexture.createView() }
            ]
        });

        render();
    }


    observers.resize = new ResizeObserver(resize);
    observers.resize.observe(canvas);


    function render(targetContext = context, dims = null) {

        if (!canRender) {
            console.warn("Cannot render; aborting render.");
            console.trace();
            return;
        }

        dims = dims || v2.of(width, height);

        const uniforms = compShader.bufferDefinitions["0,0"];
        uniforms.updateBuffers();
        const blitUniforms = blitShader.bufferDefinitions["0,0"];
        blitUniforms.updateBuffers();

        const commandEncoder = $gpu.device.createCommandEncoder();

        const computePass = commandEncoder.beginComputePass();
        computePass.setPipeline(computePipeline);
        computePass.setBindGroup(0, computeBindGroup);
        computePass.dispatchWorkgroups(
            Math.ceil(dims.x / 16),
            Math.ceil(dims.y / 16),
            1
        );
        computePass.end();

        const renderPass = commandEncoder.beginRenderPass({
            colorAttachments: [
                {
                    view: targetContext.getCurrentTexture().createView(),
                    loadOp: "clear",
                    storeOp: "store"
                }
            ]
        });

        renderPass.setPipeline(renderPipeline);
        renderPass.setBindGroup(0, renderBindGroup);
        renderPass.draw(6); // 1 quad -> 2 tris
        renderPass.end();

        $gpu.device.queue.submit([commandEncoder.finish()]);
    }

    topmost.$contextMenu = {
        items: [
            () => setControlDisplayState("block"),
            ["save frame", saveFrame],
            ["save 4x", () => offscreenRender(2)],
            ["save 9x", () => offscreenRender(3)],
            ["save 16x", () => offscreenRender(4)],
            () => setControlDisplayState("none"),
            ["exit", exitRenderer]
        ]
    };

    canvasModule.addNavigation("2d", params, render);

    topmost.$with(controlContainer, renderStack);

    return { dom: [topmost], replace: true };
}


