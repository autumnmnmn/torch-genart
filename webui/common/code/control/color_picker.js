
$css(`
.color {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding-bottom: 0.5rem;
}

.color .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--main-solid);
}

.color select {
    background: var(--main-background);
    color: var(--main-solid);
    font-family: var(--main-font);
    border: 1px solid var(--main-faded);
    border-radius: 2px;
    padding: 0.1rem 0.2rem;
    outline: none;
    cursor: pointer;
}

.color select:focus {
    border-color: var(--main-solid);
}

.color .colorbox {
    --value: #FF00FF;
    display: inline;
    background-color: var(--value);
    padding-left: 0.25rem;
    padding-right: 0.25rem;
    padding-bottom: 0.25rem;
    border-radius: 0.25rem;
}

.color .colorbox .value {
    display: inline;
    font-family: monospace;
    font-size: 0.8rem;
    color: contrast-color(var(--value));
    border-color: contrast-color(var(--value));
}

.color .axis-controls {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
}

.color .axis-controls label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--main-solid);
    font-size: 0.85rem;
    flex: 1;
}

.color .axis-controls select {
    flex: 1;
}

.color .area-container {
    position: relative;
    width: 100%;
    aspect-ratio: 1 / 1;
    /*height: 180px;
    */cursor: crosshair;
    touch-action: none;
    overflow: hidden;
}

.color .area-container canvas {
    display: block;
    width: 100%;
    height: 100%;
}

.color .cursor {
    position: absolute;
    width: 14px;
    height: 14px;
    border: 2px solid white;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    pointer-events: none;
    transition: width 0.1s, height 0.1s;
}

.color .area-container:active .cursor {
    width: 18px;
    height: 18px;
}

.color .sliders {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}

.color .slider-group label {
    display: flex;
    justify-content: space-between;
    font-size: 0.85rem;
    color: var(--main-solid);
    margin-bottom: 0.25rem;
}

.color .slider-group .val {
    font-family: monospace;
}

.color input[type=range] {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 2px;
    outline: none;
    background: transparent;
    cursor: pointer;
    border: none;
    overflow: visible;
}

.color input[type=range]::-webkit-slider-runnable-track {
    background: transparent;
    height: 0.5rem;
}

.color input[type=range]::-moz-range-track {
    background: transparent;
    height: 0.5rem;
}

.color input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 0.5rem;
    height: 1rem;
    border-radius: 2px;
    background-color: var(--main-solid);
    border: none;
}

.color input[type=range]::-moz-range-thumb {
    width: 0.5rem;
    height: 1rem;
    border-radius: 2px;
    background-color: var(--main-solid);
    box-sizing: border-box;
    border: none;
}

`);

const displayValue = (value) => Math.round(value * 100) / 100;

// Reusable 1x1 canvas to let the browser natively convert CSS strings to RGB
const _colorCanvas = document.createElement("canvas");
_colorCanvas.width = 1; _colorCanvas.height = 1;
const _colorCtx = _colorCanvas.getContext("2d", { willReadFrequently: true });

function cssToRgb(cssString) {
    _colorCtx.clearRect(0, 0, 1, 1);
    _colorCtx.fillStyle = cssString;
    _colorCtx.fillRect(0, 0, 1, 1);
    console.log(cssString);
    console.log(_colorCtx.getImageData(0, 0, 1, 1));
    return _colorCtx.getImageData(0, 0, 1, 1).data; // [r, g, b, a]
}

// TODO decouple *css* from *display string*

const SPACES = {
    oklch: {
        name: "OKLCH",
        channels: [
            { name: "Lightness", min: 0, max: 1, step: 0.01, format: v => `${Math.round(v * 100)}%` },
            { name: "Chroma", min: 0, max: 0.4, step: 0.001, format: v => v.toFixed(3) },
            { name: "Hue", min: 0, max: 360, step: 1, format: v => Math.round(v) }
        ],
        defaultVals: [0.7, 0.2, 180],
        toCss: v => `oklch(${displayValue(v[0])} ${displayValue(v[1])} ${displayValue(v[2])})`,
        fromRgb: (r, g, b) => {
            // sRGB -> Linear
            const toLin = c => {
                c /= 255;
                return c > 0.04045 ? Math.pow((c + 0.055) / 1.055, 2.4) : c / 12.92;
            };
            let lr = toLin(r), lg = toLin(g), lb = toLin(b);

            // Linear -> LMS
            let l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
            let m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
            let s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);

            // LMS -> Oklab
            let L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
            let a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
            let b_ = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;

            // Oklab -> Oklch
            let C = Math.hypot(a, b_);
            let H = Math.atan2(b_, a) * (180 / Math.PI);
            if (H < 0) H += 360;

            return [L, C, isNaN(H) ? 0 : H];
        }
    },
    hsl: {
        name: "HSL",
        channels: [
            { name: "Hue", min: 0, max: 360, step: 1, format: v => Math.round(v) },
            { name: "Saturation", min: 0, max: 100, step: 1, format: v => `${Math.round(v)}%` },
            { name: "Lightness", min: 0, max: 100, step: 1, format: v => `${Math.round(v)}%` }
        ],
        defaultVals: [180, 80, 60],
        toCss: v => `hsl(${displayValue(v[0])} ${displayValue(v[1])}% ${displayValue(v[2])}%)`,
        fromRgb: (r, g, b) => {
            r /= 255; g /= 255; b /= 255;
            const max = Math.max(r, g, b), min = Math.min(r, g, b);
            let h, s, l = (max + min) / 2;
            if (max === min) h = s = 0;
            else {
                const d = max - min;
                s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
                switch (max) {
                    case r: h = (g - b) / d + (g < b ? 6 : 0); break;
                    case g: h = (b - r) / d + 2; break;
                    case b: h = (r - g) / d + 4; break;
                }
                h *= 60;
            }
            return [h, s * 100, l * 100];
        }
    },
    rgb: {
        name: "sRGB",
        channels: [
            { name: "Red", min: 0, max: 255, step: 1, format: v => Math.round(v) },
            { name: "Green", min: 0, max: 255, step: 1, format: v => Math.round(v) },
            { name: "Blue", min: 0, max: 255, step: 1, format: v => Math.round(v) }
        ],
        defaultVals: [100, 150, 200],
        toCss: v => `rgb(${displayValue(v[0])} ${displayValue(v[1])} ${displayValue(v[2])})`,
        fromRgb: (r, g, b) => [r, g, b]
    }
};

const defaults = {
    label: "color",
    value: { space: "oklch", vals: () => [0.7, 0.2, 180] },
    onUpdate: null,
    register: null
};

export async function main(spec, panelState) {
    spec = { ...defaults, ...spec };

    const control = $div("control color");

    // -- State --
    let activeSpaceId = spec.value.space || "oklch";
    let vals = spec.value.vals; //[...(spec.value.vals || SPACES[activeSpaceId].defaultVals)];
    let sliderVals = [...vals().map(v => v || 0.0)];
    //console.log(sliderVals);
    let axisXIndex = 2; // e.g. Hue
    let axisYIndex = 1; // e.g. Chroma
    let cssWidth = 300;
    let cssHeight = 180;

    // -- DOM Elements --
    const header = $div("header");
    const titleLabel = $element("label");
    titleLabel.innerText = spec.label;
    const spaceSelect = $element("select");

    const value = $element("input");
    const colorbox = $div("colorbox");
    value.className = "value";
    header.$with(titleLabel, colorbox.$with(value));

    const axisX = $element("select");
    const axisY = $element("select");
    const labelX = $element("label");
    const labelY = $element("label");
    labelX.append("X: ", axisX);
    labelY.append("Y: ", axisY);
    const axisControls = $div("axis-controls").$with(labelX, labelY);

    const canvas = $element("canvas");
    const ctx = canvas.getContext("2d", { alpha: false });
    const cursor = $div("cursor");
    const areaContainer = $div("area-container").$with(canvas, cursor);

    const slidersContainer = $div("sliders");
    const sliderGroups = [0, 1, 2].map(i => {
        const group = $div("slider-group");
        const nameSpan = $element("span");
        const valSpan = $element("span");
        valSpan.className = "val";

        const label = $element("label").$with(nameSpan, valSpan);
        const input = $element("input");
        input.type = "range";

        group.$with(label, input);
        return { group, nameSpan, valSpan, input, index: i };
    });
    slidersContainer.$with(...sliderGroups.map(s => s.group));

    control.$with(header, spaceSelect, axisControls, areaContainer, slidersContainer);

    // -- Logic --
    for (const [id, config] of Object.entries(SPACES)) {
        const opt = $element("option");
        opt.value = id;
        opt.innerText = config.name;
        if (id === activeSpaceId) opt.selected = true;
        spaceSelect.appendChild(opt);
    }

    function initSpace(triggerCallback = true) {
        const space = SPACES[activeSpaceId];

        axisX.innerHTML = "";
        axisY.innerHTML = "";
        space.channels.forEach((ch, i) => {
            const optX = $element("option");
            optX.value = i; optX.innerText = ch.name;
            if (i === axisXIndex) optX.selected = true;
            axisX.appendChild(optX);

            const optY = $element("option");
            optY.value = i; optY.innerText = ch.name;
            if (i === axisYIndex) optY.selected = true;
            axisY.appendChild(optY);
        });

        sliderGroups.forEach((sg, i) => {
            const ch = space.channels[i];
            sg.nameSpan.innerText = ch.name;
            sg.input.min = ch.min;
            sg.input.max = ch.max;
            sg.input.step = ch.step;
        });

        renderArea();
        updateUI(triggerCallback);
    }

    function makeColor(overrideX, overrideY) {
        let temp = [...sliderVals].map(v => v || 0.0);

        if (overrideX !== undefined) temp[axisXIndex] = overrideX;
        if (overrideY !== undefined) temp[axisYIndex] = overrideY;
        return SPACES[activeSpaceId].toCss(temp);
    }

    function getSliderGradient(channelIndex) {
        const space = SPACES[activeSpaceId];
        const ch = space.channels[channelIndex];
        const numStops = ch.max > 100 ? 10 : 2;

        let stops = [];
        for(let i=0; i<=numStops; i++) {
            let temp = [...sliderVals];
            temp[channelIndex] = ch.min + (i/numStops) * (ch.max - ch.min);
            stops.push(space.toCss(temp));
        }
        return `linear-gradient(to right, ${stops.join(', ')})`;
    }

    function renderArea() {
        if (!cssWidth || !cssHeight) return;

        const space = SPACES[activeSpaceId];
        const chX = space.channels[axisXIndex];
        const chY = space.channels[axisYIndex];

        const rowHeight = 2;
        const stops = 10;

        ctx.clearRect(0, 0, cssWidth, cssHeight);

        for (let y = 0; y < cssHeight; y += rowHeight) {
            const normY = 1 - (y / (cssHeight - 1));
            const valY = chY.min + (normY * (chY.max - chY.min));

            const grad = ctx.createLinearGradient(0, 0, cssWidth, 0);
            for (let j = 0; j <= stops; j++) {
                const normX = j / stops;
                const valX = chX.min + (normX * (chX.max - chX.min));
                grad.addColorStop(normX, makeColor(valX, valY));
            }

            ctx.fillStyle = grad;
            ctx.fillRect(0, y, cssWidth, rowHeight + 0.5);
        }
    }

    function updateUI(triggerCallback = true) {
        const space = SPACES[activeSpaceId];
        const cssStr = space.toCss(sliderVals);

        colorbox.style.setProperty("--value", cssStr);
        value.value = cssStr;

        sliderGroups.forEach((sg, i) => {
            const ch = space.channels[i];
            sg.input.value = sliderVals[i];
            sg.valSpan.innerText = ch.format(sliderVals[i]);
            sg.input.style.background = getSliderGradient(i);
        });

        const chX = space.channels[axisXIndex];
        const chY = space.channels[axisYIndex];
        const normX = (sliderVals[axisXIndex] - chX.min) / (chX.max - chX.min);
        const normY = (sliderVals[axisYIndex] - chY.min) / (chY.max - chY.min);

        cursor.style.left = `${normX * 100}%`;
        cursor.style.top = `${(1 - normY) * 100}%`;

        const payload = { space: activeSpaceId, vals: [...sliderVals], css: cssStr };
        spec.onUpdate?.(payload, set, panelState, triggerCallback);
    }

    function resizeCanvas() {
        const rect = areaContainer.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        cssWidth = rect.width;
        cssHeight = rect.height;

        const dpr = window.devicePixelRatio || 1;
        canvas.width = cssWidth * dpr;
        canvas.height = cssHeight * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        renderArea();
    }

    // -- Event Listeners --

    spaceSelect.addEventListener("change", e => {
        const [r, g, b] = vals().map(v => (v || 0.0) * 255);

        activeSpaceId = e.target.value;
        sliderVals = SPACES[activeSpaceId].fromRgb(r, g, b);

        axisXIndex = 2;
        axisYIndex = 1;
        initSpace();
    });

    function handleAxisChange(changedAxis, newValue) {
        newValue = parseInt(newValue);
        if (changedAxis === 'X') {
            if (newValue === axisYIndex) { axisYIndex = axisXIndex; axisY.value = axisYIndex; }
            axisXIndex = newValue;
        } else {
            if (newValue === axisXIndex) { axisXIndex = axisYIndex; axisX.value = axisXIndex; }
            axisYIndex = newValue;
        }
        renderArea(); updateUI();
    }

    axisX.addEventListener("change", e => handleAxisChange("X", e.target.value));
    axisY.addEventListener("change", e => handleAxisChange("Y", e.target.value));

    sliderGroups.forEach(sg => {
        sg.input.addEventListener("input", e => {
            sliderVals[sg.index] = parseFloat(e.target.value);
            if (sg.index !== axisXIndex && sg.index !== axisYIndex) renderArea();
            updateUI();
        });
    });

    let isDragging = false;
    function handlePointer(e) {
        if (!isDragging) return;

        const rect = areaContainer.getBoundingClientRect();
        let x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
        let y = Math.max(0, Math.min(e.clientY - rect.top, rect.height));

        const normX = x / rect.width;
        const normY = 1 - (y / rect.height);

        const chX = SPACES[activeSpaceId].channels[axisXIndex];
        const chY = SPACES[activeSpaceId].channels[axisYIndex];

        sliderVals[axisXIndex] = chX.min + (normX * (chX.max - chX.min));
        sliderVals[axisYIndex] = chY.min + (normY * (chY.max - chY.min));

        updateUI();
    }

    areaContainer.addEventListener("pointerdown", e => {
        isDragging = true;
        areaContainer.setPointerCapture(e.pointerId);
        handlePointer(e);
    });
    areaContainer.addEventListener("pointermove", handlePointer);
    areaContainer.addEventListener("pointerup", () => isDragging = false);
    areaContainer.addEventListener("pointercancel", () => isDragging = false);

    const resizeObserver = new ResizeObserver(() => {
        resizeCanvas();
    });
    resizeObserver.observe(areaContainer);

    // -- Boot Options --

    // Set allows external resets mapping via identical signature to the slider event
    const set = (payload, doCallback = false) => {
        if (payload.space && SPACES[payload.space]) {
            activeSpaceId = payload.space;
            sliderVals = [...payload.vals];
            spaceSelect.value = activeSpaceId;
            initSpace(doCallback); // Rebuilds DOM bindings then triggers UI
        }
    };

    const hide = () => control.setAttribute("hidden", "");
    const show = () => control.removeAttribute("hidden");

    initSpace(false);

    const bundle = { dom: [control], set, show, hide };

    spec.register?.(bundle);

    return bundle;
}

