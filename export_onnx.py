import torch
import clip
import numpy as np
# 这就是那个所谓的 TextEncoder，它只是几行代码
class TextEncoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, text):
        # 它只负责调用模型里的文字编码功能
        return self.model.encode_text(text)
# 1. 加载现有的模型
device = "cpu"
model, preprocess = clip.load("models/ViT-B-32.pt", device=device)

# 2. 导出图片编码器
print("正在导出图片编码器...")
visual_model = model.visual
dummy_image = torch.randn(1, 3, 224, 224)
torch.onnx.export(
    visual_model, dummy_image, "models/clip_visual.onnx",
    export_params=True,
    opset_version=14,  # <--- 这里改为 14 或 13
    do_constant_folding=True,
    input_names=['input'], output_names=['output'],
    dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
)

# 3. 导出文字编码器
print("正在导出文字编码器...")
text_model = TextEncoder(model)
dummy_text = clip.tokenize(["a photo of a dog"])
torch.onnx.export(
    text_model, dummy_text, "models/clip_text.onnx",
    export_params=True,
    opset_version=14,  # <--- 这里也改为 14 或 13
    do_constant_folding=True,
    input_names=['input'], output_names=['output'],
    dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
)

print("✅ ONNX 模型导出成功！")