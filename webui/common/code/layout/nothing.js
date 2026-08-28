
$css(`
    nothing- {
        display: block;
        background-color: var(--main-background);
        width: 100%;
        height: 100%;
        border-radius: 0;
    }

    nothing-:focus::before {
    /*
        outline: 2px solid var(--main-faded);
        outline-offset: -2px;
        outline-radius: 0;
    */
        content: ">";
        color: var(--main-solid);
        background-color: var(--main-faded);
        line-height: 1.5em;
        width: 1.1em;
        height: 1.5em;
        border-radius: 0.2em;
        padding-left: 0.4em;
        top: 1em;
        left: 1em;
        position: relative;
        display: block;
    }
`);

customElements.define("nothing-", class extends HTMLElement {});

export async function main() {
    const backdrop = $element("nothing-");
    //const backdrop = $div("nothing");

    backdrop.$ = {
        focusable: true,
    };

    backdrop.tabIndex = 0;
    backdrop.setAttribute("role", "button");
    backdrop.setAttribute("aria-label", "Empty space. Press enter for a menu of modules to load.");

    const load = (modName, args=[]) => {
        return async () => {
            const result = await $apply(modName, backdrop.parentNode, ...args);
            if (result?.replace) {
                backdrop.remove();
            }
        }
    };

    const noth = await $prepMod("layout/nothing");
    const noth2 = {content: [noth, noth]};
    const noth3 = {content: [noth, noth, noth]};

    const menuItems = {
        projective_shift: load("gpu/proj_shift"),
        mandelbrot: load("gpu/brot"),
        lyapunov: load("gpu/lyapunov"),
        concat: load("llm/concat.vibe"),
        //prompt: load("prompt"),
        row2: load("layout/split", [noth2]),
        row3: load("layout/split", [noth3]),
        col2: load("layout/split", [{...noth2, orientation: "col"}]),
        col3: load("layout/split", [{...noth3, orientation: "col"}]),
        main: load("code/orb", ["/main.orb"]),
        spinner: load("spinner"),
        highlight: load("code/highlight"),
        pyt: load("debug/pyt")
    };

    backdrop.$contextMenu = {
        items: Object.entries(menuItems)
    };

    backdrop.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === "o") {
            e.preventDefault();
            e.stopPropagation();
            const rect = backdrop.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            document.$showMenu(backdrop);
        }
    });

    backdrop.focus();

    return {
        dom: [backdrop],
        replace: true
    };
}

