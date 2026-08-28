
const { Math: { sqrt, atan2, cos, sin, cbrt } } = globalThis;

// OkLab Magic Numbers from:
// Ottosson, Björn "A perceptual color space for image processing"
// https://bottosson.github.io/posts/oklab/
// https://web.archive.org/web/20260211105104/https://bottosson.github.io/posts/oklab/
// http://archive.today/2026.01.05-021858/https://bottosson.github.io/posts/oklab/

// From IEC 61966-2-1 5.2 Eqns (5) and (6)
function _linearize(value) {
    if (value <= 0.04045) {
        return value / 12.92;
    } else {
        let offset_scaled = (value + 0.055) / 1.055;
        return offset_scaled ** 2.4;
    }
}

// IEC 61966-2-1 5.3 Eqns (9) and (10)
function _nonlinearize(value) {
    if (value <= 0.0031308) {
        return value * 12.92;
    } else {
        let transformed = value ** (1.0 / 2.4);
        return (1.055 * transformed) - 0.055;
    }
}

class NonlinearSRGB {
    constructor({ red, green, blue }) {
        this.red = red;
        this.green = green;
        this.blue = blue;
    }

    get r() { return this.red; }
    get g() { return this.green; }
    get b() { return this.blue; }

    to_linear_srgb() {
        return new LinearSRGB({
            red: _linearize(this.red),
            green: _linearize(this.green),
            blue: _linearize(this.blue)
        });
    }
}

class LinearSRGB {
    constructor({ red, green, blue }) {
        this.red = red;
        this.green = green;
        this.blue = blue;
    }

    get r() { return this.red; }
    get g() { return this.green; }
    get b() { return this.blue; }

    to_nonlinear_srgb() {
        return new NonlinearSRGB({
            red: _nonlinearize(this.red),
            green: _nonlinearize(this.green),
            blue: _nonlinearize(this.blue)
        });
    }

    to_oklab() {
        // long/medium/short cone cell responsivity types
        let long   = 0.4122214708*this.red + 0.5363325363*this.green + 0.0514459929*this.blue;
        let medium = 0.2119034982*this.red + 0.6806995451*this.green + 0.1073969566*this.blue;
        let short  = 0.0883024619*this.red + 0.2817188376*this.green + 0.6299787005*this.blue;

        long = cbrt(long);
        medium = cbrt(medium);
        short = cbrt(short);

        return new OkLab({
            lightness:   0.2104542553*long + 0.7936177850*medium - 0.0040720468*short,
            green_red:   1.9779984951*long - 2.4285922050*medium + 0.4505937099*short,
            blue_yellow: 0.0259040371*long + 0.7827717662*medium - 0.8086757660*short
        });
    }

    to_cie_xyz() {
        return new CIEXYZ({
            x: 0.4124*this.red + 0.3576*this.green + 0.1805*this.blue,
            y: 0.2126*this.red + 0.7152*this.green + 0.0722*this.blue,
            z: 0.0193*this.red + 0.1192*this.green + 0.9505*this.blue
        });
    }
}

class OkLab {
    constructor({ lightness, green_red, blue_yellow }) {
        this.lightness = lightness;
        this.green_red = green_red; // negative=green, positive=red
        this.blue_yellow = blue_yellow; // negative=blue, positive=yellow
    }

    get L() { return this.lightness; }
    get a() { return this.green_red; }
    get b() { return this.blue_yellow; }

    to_linear_srgb() {
        let long   = this.lightness + 0.3963377774*this.green_red + 0.2158037573*this.blue_yellow;
        let medium = this.lightness - 0.1055613458*this.green_red - 0.0638541728*this.blue_yellow;
        let short  = this.lightness - 0.0894841775*this.green_red - 1.2914855480*this.blue_yellow;

        long = long ** 3;
        medium = medium ** 3;
        short = short ** 3;

        return new LinearSRGB({
            red:    4.0767416621*long - 3.3077115913*medium + 0.2309699292*short,
            green: -1.2684380046*long + 2.6097574011*medium - 0.3413193965*short,
            blue:  -0.0041960863*long - 0.7034186147*medium + 1.7076147010*short
        });
    }

    to_oklch() {
        return new OkLch({
            lightness: this.lightness,
            chroma: sqrt(this.green_red**2 + this.blue_yellow**2),
            hue: atan2(this.blue_yellow, this.green_red)
        });
    }
}

class OkLch {
    constructor({ lightness, chroma, hue }) {
        this.lightness = lightness;
        this.chroma = chroma;
        this.hue = hue;
    }

    get L() { return this.lightness; }
    get c() { return this.chroma; }
    get h() { return this.hue; }

    to_oklab() {
        return new OkLab({
            lightness: this.lightness,
            green_red: this.chroma * cos(this.hue),
            blue_yellow: this.chroma * sin(this.hue)
        });
    }
}

class CIEXYZ { // CIE 1931 XYZ
    constructor({ x, y, z }) {
        this.x = x;
        this.y = y;
        this.z = z;
    }

    to_linear_srgb() {
        return new LinearSRGB({
            red:    3.2406*this.x - 1.5372*this.y - 0.4986*this.z,
            green: -0.9689*this.x + 1.8758*this.y + 0.0415*this.z,
            blue:   0.0557*this.x - 0.2040*this.y + 1.0570*this.z
        });
    }
}

class CssColor {
    #cssString;
    #reader;

    constructor(cssString, element) {
        this.#cssString = cssString;

        if (element.$cssColorReader) {
            this.#reader = element.$cssColorReader;
        } else {
            this.#reader = $div("css-color-reader");
            element.$cssColorReader = this.#reader;

            this.#reader.style.width = "0";
            this.#reader.style.height = "0";
            this.#reader.style.position = "absolute";
            this.#reader.style.display = "block";

            this.#reader.setAttribute("aria-hidden", "true");

            element.appendChild(this.#reader);
        }

        // finally set the reader element's background color to `cssString`
        this.#reader.style.backgroundColor = cssString;
    }

    // setter for `cssString` that updates the reader's css
    set cssString(value) {
        this.#cssString = value;
        this.#reader.style.backgroundColor = value;
    }

    get cssString() {
        return this.#cssString;
    }

    to_nonlinear_srgb() {
        const computed = getComputedStyle(this.#reader).backgroundColor;

        const nums = computed.match(/[\d.]+/g);

        return new NonlinearSRGB({
            red:   parseFloat(nums[0]) / 255,
            green: parseFloat(nums[1]) / 255,
            blue:  parseFloat(nums[2]) / 255
        });
    }
}

function oklch_helix_map(
    lightness = [0.2, 0.9],
    chroma = 0.1,
    hue_start = 0.0,
    rotations = 1.0
) {
    /** returns a function [0,1] -> OkLch tracing a helix through oklch space.
        lightness ramps linearly, chroma interpolates, hue sweeps rotations*tau. */
    const [lightness_start, lightness_end] = Array.isArray(lightness) ? lightness : [lightness, lightness];
    const [chroma_start, chroma_end]       = Array.isArray(chroma)    ? chroma    : [chroma, chroma];

    function sample(t) {
        return new OkLch({
            lightness: lightness_start + t * (lightness_end - lightness_start),
            chroma:    chroma_start    + t * (chroma_end    - chroma_start),
            hue:       hue_start       + t * rotations * $tau,
        });
    }
    return sample;
}

const _CONVERSION_EDGES = new Map([
    [NonlinearSRGB, [
        [LinearSRGB, x => x.to_linear_srgb()],
    ]],
    [LinearSRGB, [
        [NonlinearSRGB, x => x.to_nonlinear_srgb()],
        [OkLab,         x => x.to_oklab()],
        [CIEXYZ,        x => x.to_cie_xyz()],
    ]],
    [OkLab, [
        [LinearSRGB, x => x.to_linear_srgb()],
        [OkLch,      x => x.to_oklch()],
    ]],
    [OkLch, [
        [OkLab, x => x.to_oklab()],
    ]],
    [CIEXYZ, [
        [LinearSRGB, x => x.to_linear_srgb()],
    ]],
    [CssColor, [
        [NonlinearSRGB, x => x.to_nonlinear_srgb()]
    ]]
]);

// map of maps of "maps" :^)
// Source -> (Target -> conversion function)
const _color_map_cache = new Map();

function color_map(source, target) {
    if (source === target) {
        return x => x;
    }

    let sourceCache = _color_map_cache.get(source);
    if (sourceCache) {
        let cached = sourceCache.get(target);
        if (cached) return cached;
    }

    let queue = [[source, []]];
    let visited = new Set([source]);

    while (queue.length > 0) {
        let [node, path] = queue.shift();
        let edges = _CONVERSION_EDGES.get(node) || [];

        for (let [neighbor, convert] of edges) {
            let new_path = [...path, convert];
            if (neighbor === target) {
                function chain_fn(x, p=new_path) {
                    for (let f of p) {
                        x = f(x);
                    }
                    return x;
                }
                if (!sourceCache) {
                    sourceCache = new Map();
                    _color_map_cache.set(source, sourceCache);
                }
                sourceCache.set(target, chain_fn);
                return chain_fn;
            }
            if (!visited.has(neighbor)) {
                visited.add(neighbor);
                queue.push([neighbor, new_path]);
            }
        }
    }

    throw new Error(`no conversion path: ${source.name} -> ${target.name}`);
}

// General-purpose convertible color
// Access requires specifying desired color space
class Color {
    #source = null;

    #nonlinear_srgb = null;
    #linear_srgb = null;
    #oklab = null;
    #oklch = null;
    #cie_xyz = null;
    #css_color = null;

    // TODO (eventually) (maybe)
    // relative transformations with provenance-chain tracking;

    constructor(value) {
        this.#source = value.constructor;
        this.#setSlot(this.#source, value);
    }

    #getSlot(type) {
        switch (type) {
            case NonlinearSRGB: return this.#nonlinear_srgb;
            case LinearSRGB:    return this.#linear_srgb;
            case OkLab:         return this.#oklab;
            case OkLch:         return this.#oklch;
            case CIEXYZ:        return this.#cie_xyz;
            case CssColor:      return this.#css_color;
            default:            return undefined;
        }
    }

    #setSlot(type, value) {
        switch (type) {
            case NonlinearSRGB: this.#nonlinear_srgb = value; break;
            case LinearSRGB:    this.#linear_srgb = value;    break;
            case OkLab:         this.#oklab = value;          break;
            case OkLch:         this.#oklch = value;          break;
            case CIEXYZ:        this.#cie_xyz = value;        break;
            case CssColor:      this.#css_color = value;      break;
        }
    }

    get(type) {
        let val = this.#getSlot(type);
        if (val !== null) return val;

        const sourceValue = this.#getSlot(this.#source);
        const conversion = color_map(this.#source, type);
        const result = conversion(sourceValue);

        this.#setSlot(type, result);
        return result;
    }

    set(value) {
        this.#nonlinear_srgb = null;
        this.#linear_srgb = null;
        this.#oklab = null;
        this.#oklch = null;
        this.#cie_xyz = null;
        this.#css_color = null;

        this.#source = value.constructor;
        this.#setSlot(this.#source, value);
    }

    get type() {
        return this.#source;
    }
}

