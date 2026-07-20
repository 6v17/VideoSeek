let currentMode = "image";
let desktopConfig = null;
let labels = {};
let imageFile = null;
let composeFiles = [];
let composeSelected = new Set();
const thumbUrlCache = new Map();
const MAX_COMPOSE_IMAGES = 12;

function setStatus(message) {
    $("status").innerText = message || "";
}

function $(id) {
    return document.getElementById(id);
}

function label(key, fallback) {
    return labels[key] || fallback || "";
}

function formatFusionValue(textPct) {
    const template = label("fusion_value", "Text {text}% · Image {image}%");
    const imagePct = 100 - textPct;
    return template.replace("{text}", String(textPct)).replace("{image}", String(imagePct));
}

function isHeicLike(file) {
    const name = String(file.name || "").toLowerCase();
    const type = String(file.type || "").toLowerCase();
    return (
        type.includes("heic") ||
        type.includes("heif") ||
        name.endsWith(".heic") ||
        name.endsWith(".heif")
    );
}

function fileKey(file) {
    return `${file.name}:${file.size}:${file.lastModified}`;
}

function maxComposeImages() {
    const configured = Number(desktopConfig && desktopConfig.max_compose_images);
    return Number.isFinite(configured) && configured > 0 ? configured : MAX_COMPOSE_IMAGES;
}

function openImagePicker() {
    $("file-input").click();
}

function openComposePicker() {
    $("compose-file-input").click();
}

async function previewViaServer(file, silent=false) {
    if (!silent) {
        setStatus("正在由电脑生成预览...");
    }
    const formData = new FormData();
    formData.append("token", uploadToken);
    formData.append("file", file);
    const response = await fetch("/preview", { method: "POST", body: formData });
    if (!response.ok) {
        if (!silent) {
            setStatus("预览失败，但仍可发送。");
        }
        return null;
    }
    if (!silent) {
        setStatus("");
    }
    return await response.blob();
}

async function filePreviewUrl(file) {
    const key = fileKey(file);
    if (thumbUrlCache.has(key)) {
        return thumbUrlCache.get(key);
    }
    let url = "";
    if (isHeicLike(file)) {
        const converted = await previewViaServer(file, true);
        url = converted ? URL.createObjectURL(converted) : "";
    } else {
        url = URL.createObjectURL(file);
    }
    thumbUrlCache.set(key, url);
    return url;
}

async function setImagePreview(file) {
    const preview = $("image-preview");
    const drop = $("image-drop");
    const placeholder = $("image-drop-placeholder");
    if (preview._objectUrl) {
        URL.revokeObjectURL(preview._objectUrl);
        preview._objectUrl = null;
    }

    let blob = file;
    if (isHeicLike(file)) {
        const converted = await previewViaServer(file);
        if (!converted) {
            placeholder.style.display = "block";
            preview.style.display = "none";
            drop.classList.remove("has-image");
            return;
        }
        blob = converted;
    }

    preview._objectUrl = URL.createObjectURL(blob);
    preview.src = preview._objectUrl;
    preview.style.display = "block";
    placeholder.style.display = "none";
    drop.classList.add("has-image");
    setStatus("");
}

function handleImageFileInput() {
    const input = $("file-input");
    if (!input.files || !input.files[0]) {
        return;
    }
    imageFile = input.files[0];
    setImagePreview(imageFile);
    input.value = "";
}

function handleComposeFileInput() {
    addComposeFiles($("compose-file-input").files);
    $("compose-file-input").value = "";
}

function addComposeFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) {
        return;
    }
    const existing = new Set(composeFiles.map(fileKey));
    for (const file of incoming) {
        const key = fileKey(file);
        if (existing.has(key)) {
            continue;
        }
        if (composeFiles.length >= maxComposeImages()) {
            setStatus(`组合搜索最多 ${maxComposeImages()} 张参考图。`);
            break;
        }
        composeFiles.push(file);
        existing.add(key);
    }
    renderComposeStrip();
    updateFusionVisibility();
}

function toggleComposeSelection(key) {
    if (composeSelected.has(key)) {
        composeSelected.delete(key);
    } else {
        composeSelected.add(key);
    }
    renderComposeStrip();
}

function removeSelectedComposeImages() {
    if (!composeSelected.size) {
        setStatus(label("remove_selected_empty", "请先勾选要删除的图片。"));
        return;
    }
    composeFiles = composeFiles.filter(file => !composeSelected.has(fileKey(file)));
    composeSelected.clear();
    renderComposeStrip();
    updateFusionVisibility();
}

async function renderComposeStrip() {
    const wrap = $("compose-strip-wrap");
    const strip = $("compose-image-strip");
    strip.innerHTML = "";

    if (!composeFiles.length) {
        wrap.style.display = "none";
        updateRemoveSelectedButton();
        return;
    }

    wrap.style.display = "block";
    for (const file of composeFiles) {
        const key = fileKey(file);
        const chip = document.createElement("div");
        chip.className = "image-chip" + (composeSelected.has(key) ? " selected" : "");
        chip.onclick = () => toggleComposeSelection(key);

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "chip-check";
        checkbox.checked = composeSelected.has(key);
        checkbox.onclick = event => {
            event.stopPropagation();
            toggleComposeSelection(key);
        };

        const img = document.createElement("img");
        img.alt = file.name;
        img.src = await filePreviewUrl(file);

        chip.appendChild(checkbox);
        chip.appendChild(img);
        strip.appendChild(chip);
    }
    updateRemoveSelectedButton();
}

function updateRemoveSelectedButton() {
    const count = composeSelected.size;
    const button = $("btn-remove-selected");
    const base = label("remove_selected", "删除选中");
    button.disabled = count === 0;
    button.innerText = count ? `${base} (${count})` : base;
}

function currentQuery() {
    if (currentMode === "text") {
        return String($("text-query-input").value || "").trim();
    }
    if (currentMode === "dialogue") {
        return String($("dialogue-query-input").value || "").trim();
    }
    if (currentMode === "compose") {
        return String($("compose-query-input").value || "").trim();
    }
    return "";
}

function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll("[data-mode-tab]").forEach(button => {
        button.classList.toggle("active", button.dataset.modeTab === mode);
    });
    $("panel-image").classList.toggle("active", mode === "image");
    $("panel-text").classList.toggle("active", mode === "text");
    $("panel-dialogue").classList.toggle("active", mode === "dialogue");
    $("panel-compose").classList.toggle("active", mode === "compose");
    $("image-mode-block").style.display = mode === "image" ? "block" : "none";
    // Text + compose: frame / chunk only.
    $("text-mode-block").style.display = (mode === "text" || mode === "compose") ? "block" : "none";
    $("dialogue-mode-block").style.display = mode === "dialogue" ? "block" : "none";
    updateFusionVisibility();
    updateSubmitLabel();
}

function fillSelect(selectId, options, selectedId) {
    const select = $(selectId);
    if (!select) {
        return;
    }
    const previous = String(select.value || selectedId || "");
    select.innerHTML = "";
    (options || []).forEach(item => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.label || item.id;
        select.appendChild(option);
    });
    const preferred = String(selectedId || previous || "");
    if (preferred && Array.from(select.options).some(opt => opt.value === preferred)) {
        select.value = preferred;
    } else if (select.options.length) {
        select.selectedIndex = 0;
    }
}

function imageModeLabel(modeId) {
    const modes = (desktopConfig && desktopConfig.image_search_modes) || [];
    const hit = modes.find(item => item.id === modeId);
    return (hit && hit.label) || modeId || "";
}

function textModeLabel(modeId) {
    const modes = (desktopConfig && desktopConfig.text_search_modes) || [];
    const hit = modes.find(item => item.id === modeId);
    return (hit && hit.label) || modeId || "";
}

function dialogueModeLabel(modeId) {
    const modes = (desktopConfig && desktopConfig.dialogue_search_modes) || [];
    const hit = modes.find(item => item.id === modeId);
    return (hit && hit.label) || modeId || "";
}

function updateFusionVisibility() {
    const show = currentMode === "compose" && currentQuery() && composeFiles.length > 0;
    $("fusion-block").style.display = show ? "block" : "none";
    if (show) {
        updateFusionLabel();
    }
}

function updateFusionLabel() {
    const textPct = Number($("fusion-slider").value || 50);
    $("fusion-value").innerText = formatFusionValue(textPct);
}

function updateSubmitLabel() {
    const tabLabels = {
        image: label("tab_image", "图搜"),
        text: label("tab_text", "文搜"),
        compose: label("tab_compose", "组合"),
        dialogue: label("tab_dialogue", "字幕"),
    };
    $("submit-btn").innerText = `发送并${tabLabels[currentMode] || "搜索"}`;
}

function validateBeforeSubmit() {
    if (currentMode === "image" && !imageFile) {
        alert("请先选择图片");
        return false;
    }
    if (currentMode === "text" && !currentQuery()) {
        alert("请输入搜索描述");
        return false;
    }
    if (currentMode === "dialogue" && !currentQuery()) {
        alert("请输入字幕关键词");
        return false;
    }
    if (currentMode === "compose" && !currentQuery() && composeFiles.length === 0) {
        alert("组合搜索需要文字和/或图片");
        return false;
    }
    return true;
}

function applyLabels() {
    document.querySelectorAll("[data-mode-tab='image']").forEach(el => {
        el.innerText = label("tab_image", "图搜");
    });
    document.querySelectorAll("[data-mode-tab='text']").forEach(el => {
        el.innerText = label("tab_text", "文搜");
    });
    document.querySelectorAll("[data-mode-tab='compose']").forEach(el => {
        el.innerText = label("tab_compose", "组合");
    });
    document.querySelectorAll("[data-mode-tab='dialogue']").forEach(el => {
        el.innerText = label("tab_dialogue", "字幕");
    });
    $("text-query-input").placeholder = label("description_hint", "用文本描述你想找的画面…");
    $("dialogue-query-input").placeholder = label(
        "dialogue_hint",
        "输入字幕里出现过的词或短句…"
    );
    $("compose-query-input").placeholder = label("description_hint", "用文本补充搜索意图，可与辅助图搭配使用");
    $("btn-add-images").innerText = label("add_images", "添加图片");
    $("fusion-title").innerText = label("fusion_title", "文图权重");
    $("fusion-hint").innerText = label("fusion_hint", "同时有描述和辅助图时才会用到。");
    $("fusion-text-label").innerText = label("fusion_text", "偏文本");
    $("fusion-image-label").innerText = label("fusion_image", "偏图片");
    $("image-drop-hint").innerText = label("image_drop_hint", "拖入图片到这里\n或点击选择图片");
    $("image-mode-label").innerText = label("image_mode_label", "图搜模式");
    $("text-mode-label").innerText = label("text_mode_label", "检索粒度");
    $("dialogue-mode-label").innerText = label("dialogue_mode_label", "匹配方式");
    updateRemoveSelectedButton();
    updateFusionLabel();
    updateSubmitLabel();
}

async function loadDesktopConfig() {
    try {
        const response = await fetch(`/config?token=${encodeURIComponent(uploadToken)}`);
        if (!response.ok) {
            return;
        }
        desktopConfig = await response.json();
        labels = desktopConfig.labels || {};
        applyLabels();
        fillSelect(
            "image-search-mode",
            desktopConfig.image_search_modes,
            desktopConfig.image_search_mode || "frame"
        );
        fillSelect(
            "text-search-mode",
            desktopConfig.text_search_modes,
            desktopConfig.search_mode || "frame"
        );
        fillSelect(
            "dialogue-search-mode",
            desktopConfig.dialogue_search_modes,
            desktopConfig.dialogue_search_mode || "exact"
        );

        const imageMode = imageModeLabel(desktopConfig.image_search_mode || "frame");
        const textMode = textModeLabel(desktopConfig.search_mode || "frame");
        const dialogueMode = dialogueModeLabel(desktopConfig.dialogue_search_mode || "exact");
        const scope = desktopConfig.scope_mode === "selected"
            ? label("scope_selected", "已选范围")
            : label("scope_all", "全部");
        const dialogueScope = desktopConfig.dialogue_scope_mode === "selected"
            ? label("scope_selected", "已选范围")
            : label("scope_all", "全部");
        $("desktop-hint").innerText =
            `电脑当前：图搜=${imageMode} · 文搜=${textMode} · 字幕=${dialogueMode} · 画面范围=${scope} · 字幕范围=${dialogueScope}`;
    } catch (_error) {
        $("desktop-hint").innerText = "已连接电脑；可在下方选择与电脑一致的搜索模式。";
    }
}

async function submitSearch() {
    if (!validateBeforeSubmit()) {
        return;
    }

    const button = $("submit-btn");
    button.disabled = true;
    const oldLabel = button.innerText;
    button.innerText = "发送中...";
    setStatus("正在发送到电脑端...");

    const formData = new FormData();
    formData.append("token", uploadToken);
    formData.append("search_kind", currentMode);
    formData.append("query", currentQuery());
    if (currentMode === "image") {
        formData.append("image_search_mode", String($("image-search-mode").value || "frame"));
    }
    if (currentMode === "text" || currentMode === "compose") {
        formData.append("search_mode", String($("text-search-mode").value || "frame"));
    }
    if (currentMode === "dialogue") {
        formData.append(
            "dialogue_search_mode",
            String($("dialogue-search-mode").value || "exact")
        );
    }
    if (currentMode === "compose") {
        formData.append("text_weight", String($("fusion-slider").value || "50"));
        composeFiles.forEach(file => formData.append("files", file));
    } else if (currentMode === "image" && imageFile) {
        formData.append("file", imageFile);
    }

    try {
        const response = await fetch("/search", { method: "POST", body: formData });
        let payload = {};
        try {
            payload = await response.json();
        } catch (_error) {
            payload = {};
        }
        if (!response.ok || !payload.ok) {
            throw new Error(payload.detail || payload.message || "上传失败");
        }
        setStatus(payload.message || "已发送，请在电脑端查看结果。");
    } catch (error) {
        setStatus(error.message || "连接失败，请确认和电脑在同一局域网。");
    } finally {
        button.disabled = false;
        button.innerText = oldLabel;
    }
}

function clearForm() {
    imageFile = null;
    composeFiles = [];
    composeSelected.clear();
    thumbUrlCache.forEach(url => {
        if (url) {
            URL.revokeObjectURL(url);
        }
    });
    thumbUrlCache.clear();

    const preview = $("image-preview");
    if (preview._objectUrl) {
        URL.revokeObjectURL(preview._objectUrl);
        preview._objectUrl = null;
    }
    preview.removeAttribute("src");
    preview.style.display = "none";
    $("image-drop-placeholder").style.display = "block";
    $("image-drop").classList.remove("has-image");

    $("text-query-input").value = "";
    $("dialogue-query-input").value = "";
    $("compose-query-input").value = "";
    $("compose-image-strip").innerHTML = "";
    $("compose-strip-wrap").style.display = "none";
    $("fusion-slider").value = "50";
    $("file-input").value = "";
    $("compose-file-input").value = "";
    updateRemoveSelectedButton();
    updateFusionVisibility();
    setStatus("");
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-mode-tab]").forEach(button => {
        button.addEventListener("click", () => setMode(button.dataset.modeTab));
    });
    $("text-query-input").addEventListener("input", updateFusionVisibility);
    $("compose-query-input").addEventListener("input", updateFusionVisibility);
    $("fusion-slider").addEventListener("input", updateFusionLabel);
    setMode("image");
    loadDesktopConfig();
});
