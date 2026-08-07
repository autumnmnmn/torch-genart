
$css(`

.control-panel {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding: 0.5rem;
    font-family: var(--main-font);
    color: var(--main-solid);
    overflow-y: scroll;
    height: 100%;
    width: fit-content;
    padding-right: 1rem;
}

.control-panel > * {
    max-width: 300px;
}

.control-panel legend {
    line-height: 1rem;
    margin: auto;
    border-bottom: 3px double var(--main-solid);
    padding-top: 0.5rem;
    padding-bottom: 0.2rem;
    padding-left: 0.5rem;
    padding-right: 0.5rem;
}

.control {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}

.control {
    border-left: 1px solid var(--main-faded);
    padding-left: 0.5rem;
}

.control:has(:focus) {
    border-left: 3px solid var(--main-solid);
    padding-left: calc(0.5rem - 2px);
}

.control > .control, .control > .control:has(:focus) {
    border-left: none;
    padding-left: 0;
    padding-top: 0.5rem;
}

.control[hidden] {
    display: none;
}

@media (max-width: 768px) {
    .control-panel {
        flex-direction: row;
        flex-wrap: wrap;
        width: 100%;
    }

    .control {
        width: 45%;
        max-width: 45%;
    }
}

`);

async function createControl(target, spec, state) {
    return await $apply(`control/${spec.type}`, target, spec, state);
}

export async function main(name, controls) {
    const id = name.toLowerCase().replace(/\s+/g, "-");

    const container = document.createElement("fieldset");
    container.className = "control-panel";
    container.setAttribute("aria-labelledby", id);

    const legend = document.createElement("legend");
    legend.id = id;
    legend.innerText = name;
    container.appendChild(legend);

    const controlState = {};


    for (const control of controls) {
        const name = control.name ?? control.label;
        controlState[name] = await createControl(container, control, controlState);
        if (control.hidden) {
            controlState[name].hide?.();
        }
    }

    return {
        dom: [container],
        replace: true,
        controls: controlState
    };
}

