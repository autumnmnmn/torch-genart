
$css(`

.toggle {
    display: block;
    line-height: 1.5rem;
}

.toggle label {
    color: var(--main-solid);
    line-height: 1em;
    min-height: 1em;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    cursor: pointer;
}

.toggle input[type="checkbox"] {
    user-select: none;
    vertical-align: text-bottom;

    accent-color: var(--main-solid);
    cursor: pointer;

    width: 1.25em;
    height: 1.25em;

    margin-bottom: 0.125em;

    appearance: none;
    background-color: transparent;
    border: none;
    outline: none;

    position: relative;
}

.toggle input[type="checkbox"]:checked {
    background-color: var(--main-solid);
}

.toggle input[type="checkbox"]:not(:checked) {
    background-color: var(--main-faded);
}

.toggle label {
    color: var(--main-solid);
    line-height: 1em;
    cursor: text;
    display: inline;
    padding-right: 0.5em;
}

.toggle .status {
    color: var(--main-faded);
    padding-left: 0.5em;
}

.toggle:has(input[type="checkbox"]:checked) .status {
    color: var(--main-solid);
}

.toggle .box {
    user-select: none;
    border-bottom: 1px solid var(--main-faded);
    cursor: pointer;
    display: inline-block;
    vertical-align: bottom;
}

.toggle:has(input[type="checkbox"]:checked) .box {
    border-bottom: 1px solid var(--main-solid);
}


`);

const defaults = {
    label: "toggle",
    value: false,
    states: ["off", "on"],
    onUpdate: null,
    register: null,
    subcontrol: null
};

export async function main(spec, panelState) {
    spec = { ...defaults, ...spec };

    const control = document.createElement("div");
    control.className = "control toggle";

    const label = document.createElement("label");
    label.innerText = spec.label + ":";

    const status = $element("span");
    status.innerText = spec.value ? spec.states[1] : spec.states[0];
    status.className = "status";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = spec.value;
    checkbox.setAttribute("aria-label", spec.label);
    checkbox.addEventListener("change", () => {
        spec.onUpdate?.(checkbox.checked, panelState);
        status.innerText = checkbox.checked ? spec.states[1] : spec.states[0];
    });

    const box_container = $element("span");
    box_container.className = "box";
    const longerState = spec.states.reduce((a, b) => a.length >= b.length ? a : b);
    box_container.style = `width: calc(${longerState.length}ch + 2em)`;


    box_container.addEventListener("pointerdown", (e) => {
        if (e.target !== checkbox) {
            e.preventDefault();
            checkbox.focus();
        }
    });

    box_container.addEventListener("click", (e) => {
        if (e.target !== checkbox) {
            checkbox.click();
        }
    });

    const dom = [
        control.$with(
            label,
            box_container.$with(checkbox, status)
        )
    ];

    if (spec.subcontrols !== null) {
        for(const subcontrol of spec.subcontrols) {
            const name = subcontrol.name ?? subcontrol.label;
            panelState[name] = await $apply(`control/${subcontrol.type}`, control, subcontrol, panelState);
            if (subcontrol.hidden) {
                panelState[name].hide?.();
            }
        }
    }

    const set = () => {/*TODO*/};

    const bundle = { set, dom };

    spec.register?.(bundle);

    return bundle;
}
