
"use strict";

$css(`
    .combiner-pane {
        flex: 1;
        overflow-y: auto;
        padding: 24px;
        display: flex;
        flex-wrap: wrap;
        align-content: flex-start;
        gap: 24px;
        position: relative;
        background-color: var(--main-background);
        color: var(--main-solid);
        font-family: var(--main-font, monospace);
        height: 100%;
        box-sizing: border-box;
    }

    .preview-pane {
        width: 100%;
        height: 100%;
        background-color: var(--main-background);
        position: relative;
    }

    /* Group Card */
    .combiner-pane .file-group {
        border: 2px dashed var(--main-faded);
        border-radius: 12px;
        padding: 20px;
        width: 350px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        transition: border-color 0.2s, background-color 0.2s;
        background-color: var(--main-background);
    }

    .combiner-pane .file-group.drag-over {
        border-color: var(--main-solid);
        background-color: var(--main-faded);
    }

    /* Header & Inputs */
    .combiner-pane .group-header-container {
        display: flex;
        gap: 8px;
        align-items: center;
    }

    .combiner-pane .group-title-input {
        flex: 1;
        background: transparent;
        border: 1px dashed transparent;
        color: var(--main-solid);
        font-size: 1.2em;
        font-weight: bold;
        font-family: inherit;
        text-align: center;
        border-radius: 6px;
        padding: 4px;
        width: 100%;
        transition: background 0.2s, border-color 0.2s;
    }

    .combiner-pane .group-title-input:hover,
    .combiner-pane .group-title-input:focus {
        border-color: var(--main-faded);
        outline: none;
        background: var(--main-faded);
    }

    .combiner-pane .delete-group-btn {
        background: transparent;
        border: none;
        color: var(--main-solid);
        cursor: pointer;
        font-size: 1.2em;
        padding: 4px;
        border-radius: 4px;
    }

    .combiner-pane .delete-group-btn:hover {
        background-color: var(--main-faded);
    }

    /* File List */
    .combiner-pane .file-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
        flex-grow: 1;
        min-height: 100px;
    }

    .combiner-pane .file-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: var(--main-faded);
        border-radius: 6px;
        font-size: 0.9em;
        padding-left: 0.5rem;
        padding-top: 0.125rem;
        padding-right: 0.25rem;
        padding-bottom: 0.125rem;
    }

    .combiner-pane .file-name {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Buttons */
    .combiner-pane button {
        background-color: var(--main-background);
        color: var(--main-solid);
        border: 1px solid var(--main-faded);
        border-radius: 6px;
        cursor: pointer;
        transition: background-color 0.2s;
    }

    .combiner-pane button:hover {
        background-color: var(--main-faded);
    }

    .combiner-pane .actions {
        display: flex;
        gap: 12px;
    }

    .combiner-pane .actions button {
        flex: 1;
        height: 1.75rem;
    }

    .combiner-pane .remove-btn {
        padding-top: 0;
        padding-bottom: 0.5em;
        padding-left: 0.5em;
        padding-right: 0.5em;
    }

    .combiner-pane .add-group-btn {
        border: 2px dashed var(--main-faded);
        background-color: transparent;
        color: var(--main-faded);
        font-size: 1.2em;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 150px;
        width: 350px;
        height: fit-content;
    }

    .combiner-pane .add-group-btn:hover {
        border-color: var(--main-solid);
        background-color: var(--main-faded);
        color: var(--main-solid);
    }

    /* Toast */
    .combiner-toast {
        position: fixed;
        bottom: 24px;
        left: 24px;
        background: var(--main-solid);
        color: var(--main-background);
        padding: 12px 20px;
        border-radius: 8px;
        font-weight: bold;
        display: none;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        z-index: 100;
    }
`);

export async function main() {
    const leftPane = $div("combiner-pane");
    leftPane.$preventCollapse = true;

    const previewPane = $div("preview-pane");

    const addGroupBtn = $element("button");
    addGroupBtn.className = "add-group-btn";
    addGroupBtn.innerText = "new group";

    const toast = $div("combiner-toast");

    leftPane.$with(addGroupBtn, toast);

    let topmost = leftPane;
    let groupInstances = [];
    let currentPreviewId = null;
    let toastTimeout;

    // -- Global State Management --

    function showToast(msg) {
        toast.textContent = msg;
        toast.style.display = "block";
        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => { toast.style.display = "none"; }, 4000);
    }

    async function showPreview(title, markdown) {
        if (!topmost.isConnected) {
            topmost = leftPane;
        }

        let editor = topmost.querySelector(".highlight-editor");

        if (!editor) {

            const anchorParent = topmost.parentNode;
            const anchorNext = topmost.nextSibling;

            // Preview is not currently shown (or was collapsed). Spin up the split view!
            const split = await $mod("layout/split", {
                content: [leftPane, previewPane],
                percents: [60, 40]
            });

            anchorParent.insertBefore(split.topmost, anchorNext);
            topmost = split.topmost;

            previewPane.innerHTML = "";
            await $apply("code/highlight", previewPane, markdown || "// empty");

            editor = previewPane.querySelector(".highlight-editor");
        } else {
            // Already rendering, update gracefully
            editor.value = markdown || "// empty";
            editor.dispatchEvent(new Event("input"));
        }
    }

    function saveAll() {
        const state = groupInstances.map(g => g.getState());
        try {
            localStorage.setItem('fileCombinerState', JSON.stringify(state));
        } catch (e) {
            console.warn("Storage quota exceeded!", e);
            showToast("Storage quota exceeded! Changes won't persist on reload.");
        }
    }

    function addGroup(initialData, skipSave = false) {
        const group = createFileGroup(initialData);
        groupInstances.push(group);
        leftPane.insertBefore(group.element, addGroupBtn);
        if (!skipSave) saveAll();
    }

    // -- Factory Component --

        if (!topmost.isConnected) {
            topmost = leftPane;
        }
    function createFileGroup(initialData) {
        const id = initialData.id || Math.random().toString(36).substring(2);
        let title = initialData.title || "new group";
        let files = initialData.files || [];

        const groupContainer = $div("file-group");

        const headerContainer = $div("group-header-container");
        const titleInput = $element("input");
        titleInput.className = "group-title-input";
        titleInput.value = title;
        titleInput.oninput = (e) => {
            title = e.target.value;
            triggerUpdate();
        };

        const deleteGroupBtn = $element("button");
        deleteGroupBtn.className = "delete-group-btn";
        deleteGroupBtn.innerHTML = "🗑️";
        deleteGroupBtn.title = "delete group";
        deleteGroupBtn.onclick = () => {
            groupContainer.remove();
            groupInstances = groupInstances.filter(g => g.id !== id);

            if (currentPreviewId === id) {
                let editor = topmost.querySelector(".highlight-editor");
                if (editor) {
                    editor.value = "// select a group to preview";
                    editor.dispatchEvent(new Event("input"));
                }
                currentPreviewId = null;
            }
            saveAll();
        };

        headerContainer.$with(titleInput, deleteGroupBtn);

        const fileList = $element("ul");
        fileList.className = "file-list";

        const topActions = $div("actions");
        const previewBtn = $element("button");
        previewBtn.textContent = "preview";
        previewBtn.onclick = () => {
            currentPreviewId = id;
            showPreview(title, generateMarkdown());
        };

        const copyBtn = $element("button");
        copyBtn.textContent = "copy";

        topActions.$with(previewBtn, copyBtn);

        const bottomActions = $div("actions");
        const clearBtn = $element("button");
        clearBtn.textContent = "clear files";
        clearBtn.onclick = () => {
            files = [];
            renderFiles();
            triggerUpdate();
        };

        bottomActions.$with(clearBtn);

        groupContainer.$with(headerContainer, fileList, topActions, bottomActions);

        // D&D Logic
        groupContainer.addEventListener("dragover", (e) => {
            e.preventDefault();
            groupContainer.classList.add("drag-over");
        });

        groupContainer.addEventListener("dragleave", (e) => {
            e.preventDefault();
            groupContainer.classList.remove("drag-over");
        });

        groupContainer.addEventListener("drop", async (e) => {
            e.preventDefault();
            groupContainer.classList.remove("drag-over");
            if (!e.dataTransfer || !e.dataTransfer.files) return;

            const droppedFiles = Array.from(e.dataTransfer.files);
            for (const file of droppedFiles) {
                const buffer = await file.arrayBuffer();
                try {
                    const decoder = new TextDecoder("utf-8", { fatal: true });
                    files.push({
                        id: Math.random().toString(36).substring(2),
                        name: file.name,
                        content: decoder.decode(buffer)
                    });
                } catch (err) {
                    console.warn(`Skipping: ${file.name} - invalid UTF-8`);
                }
            }

            renderFiles();
            triggerUpdate();
        });

        // Reactivity
        function renderFiles() {
            fileList.innerHTML = "";
            if (files.length === 0) {
                const emptyMsg = $div();
                emptyMsg.style.opacity = "0.5";
                emptyMsg.style.textAlign = "center";
                emptyMsg.style.marginTop = "20px";
                emptyMsg.textContent = "[drop files here]";
                fileList.appendChild(emptyMsg);
                return;
            }

            files.forEach((f) => {
                const li = $element("li");
                li.className = "file-item";

                const nameSpan = $element("span");
                nameSpan.className = "file-name";
                nameSpan.textContent = f.name;
                nameSpan.title = f.name;

                const removeBtn = $element("button");
                removeBtn.className = "remove-btn";
                removeBtn.textContent = "✕";
                removeBtn.onclick = () => {
                    files = files.filter((x) => x.id !== f.id);
                    renderFiles();
                    triggerUpdate();
                };

                li.$with(nameSpan, removeBtn);
                fileList.appendChild(li);
            });
        }

        function generateMarkdown() {
            return files.map((f) => {
                const backtickMatches = f.content.match(/`{3,}/g);
                let fenceLength = 3;
                if (backtickMatches) {
                    fenceLength = Math.max(...backtickMatches.map((m) => m.length)) + 1;
                }
                const fence = "`".repeat(fenceLength);

                let ext = "";
                const parts = f.name.split(".");
                if (parts.length > 1) {
                    ext = parts.pop();
                }

                return `### \`${f.name}\`\n${fence}${ext}\n${f.content}\n${fence}\n`;
            }).join("\n");
        }

        function triggerUpdate() {
            saveAll();
            // actively hydrate the right-side panel if this is currently being looked at
            // ...but ONLY if the preview pane hasn't been collapsed away by the user!
            if (currentPreviewId === id) {
                if (!topmost.isConnected) {
                    topmost = leftPane;
                }

                let editor = topmost.querySelector(".highlight-editor");
                if (editor) {
                    showPreview(title, generateMarkdown());
                } else {
                    currentPreviewId = null; // deselect if user closed it manually
                }
            }
        }

        copyBtn.onclick = async () => {
            if (files.length === 0) return;
            try {
                await navigator.clipboard.writeText(generateMarkdown());
                const originalText = copyBtn.textContent;
                copyBtn.textContent = "Copied! ˶ᵔ ᵕ ᵔ˶";
                setTimeout(() => { copyBtn.textContent = originalText; }, 2000);
            } catch (err) {
                console.error("clipboard write failed :(", err);
                copyBtn.textContent = "Failed :(";
            }
        };

        renderFiles();

        return {
            id,
            element: groupContainer,
            getState: () => ({ id, title, files })
        };
    }

    // -- Initialization --

    addGroupBtn.onclick = () => addGroup({});

    const saved = localStorage.getItem('fileCombinerState');
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed) && parsed.length > 0) {
                parsed.forEach(data => addGroup(data, true));
            } else {
                addGroup({ title: 'Group A' }, true);
            }
        } catch (e) {
            console.warn("corrupted localstorage, dropping state");
            addGroup({ title: 'Group A' }, true);
        }
    } else {
        addGroup({ title: 'Group A' }, true);
    }

    function exitTool() {
        const target = topmost.parentNode;
        target.replaceChildren();
        $apply("layout/nothing", target);
    }

    topmost.$contextMenu = {
        items: [
            ["exit", exitTool]
        ]
    };

    return {
        dom: [topmost],
        replace: true
    };
}

