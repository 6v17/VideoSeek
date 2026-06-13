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
    $("panel-compose").classList.toggle("active", mode === "compose");
    updateFusionVisibility();
    updateSubmitLabel();
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
    $("text-query-input").placeholder = label("description_hint", "用文本描述你想找的画面…");
    $("compose-query-input").placeholder = label("description_hint", "用文本补充搜索意图，可与辅助图搭配使用");
    $("btn-add-images").innerText = label("add_images", "添加图片");
    $("fusion-title").innerText = label("fusion_title", "文图权重");
    $("fusion-hint").innerText = label("fusion_hint", "同时有描述和辅助图时才会用到。");
    $("fusion-text-label").innerText = label("fusion_text", "偏文本");
    $("fusion-image-label").innerText = label("fusion_image", "偏图片");
    $("image-drop-hint").innerText = label("image_drop_hint", "拖入图片到这里\n或点击选择图片");
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

        const mode = desktopConfig.search_mode === "chunk" ? "片段" : "帧";
        const scope = desktopConfig.scope_mode === "selected" ? "已选范围" : "全部库";
        const precision = desktopConfig.search_precision_default === "precise" ? "开" : "关";
        $("desktop-hint").innerText =
            `电脑端：${mode}模式 · ${scope} · 图搜精搜=${precision} · 组合最多${maxComposeImages()}图`;
    } catch (_error) {
        $("desktop-hint").innerText = "已连接电脑，范围/帧片段模式跟随电脑设置。";
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
