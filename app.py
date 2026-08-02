import os
import io
import json
import re
import asyncio
from typing import List
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import google.generativeai as genai
from PIL import Image

app = FastAPI()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def process_single_image(image_bytes: bytes, filename: str) -> dict:
    try:
        if not GEMINI_API_KEY:
            return {"status": "error", "filename": filename, "message": "環境變數缺少 GEMINI_API_KEY"}

        image = Image.open(io.BytesIO(image_bytes))
        image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='JPEG', quality=80)
        final_bytes = img_byte_arr.getvalue()

        prompt = """
        請分析這張娃娃機計數器照片，並提取以下三個資訊：
        1. machine_id: 位於螢幕正下方白底黑框貼紙上的「大數字標籤」。
        2. raw_a: LCD螢幕中 A 行右側的原始數字。
        3. raw_c: LCD螢幕中 C 行右側的原始數字。
        【1 與 7 嚴格幾何特徵分辨規則】：
        - 數字 1 的頂部是平的、空的，完全沒有點亮橫槓。
        - 數字 7 的頂部明確點亮了一條水平橫槓。
        請嚴格只回傳 JSON 格式：
        {"machine_id": 數字, "raw_a": 數字, "raw_c": 數字}
        """

        # 直接指定最穩定的正式商用模型
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": final_bytes}])
        
        match = re.search(r'\{.*\}', response.text.strip(), re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return {
                "status": "success", "filename": filename,
                "machine_id": int(data.get("machine_id", 0)),
                "raw_a": int(data.get("raw_a", 0)),
                "raw_c": int(data.get("raw_c", 0))
            }
        else:
            return {"status": "error", "filename": filename, "message": "AI 回傳格式異常"}

    except Exception as e:
        return {"status": "error", "filename": filename, "message": str(e)}

@app.get("/", response_class=HTMLResponse)
async def index_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AC表極速辨識系統</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; margin: 0; padding: 20px; display: flex; justify-content: center; }
            .card { background: white; width: 100%; max-width: 600px; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); box-sizing: border-box; }
            h2 { margin-top: 0; color: #1d1d1f; text-align: center; }
            .file-drop-area { border: 2px dashed #0071e3; border-radius: 8px; padding: 35px 20px; text-align: center; background: #f0f7ff; cursor: pointer; margin-bottom: 20px; }
            .file-drop-area input { display: none; }
            .upload-icon { font-size: 40px; margin-bottom: 10px; display: block; }
            .btn { width: 100%; padding: 14px; background: #0071e3; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.3s; }
            .btn:disabled { background: #ccc; cursor: not-allowed; }
            .progress-box { display: none; margin-top: 20px; text-align: center; }
            .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #0071e3; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin: 10px auto; }
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            .error-msg { color: #d60000; font-weight: bold; margin-top: 15px; display: none; white-space: pre-wrap; background: #ffebeb; padding: 12px; border-radius: 8px; font-size: 14px; }
            .result-area { margin-top: 25px; display: none; }
            textarea { width: 100%; height: 350px; font-family: monospace; font-size: 16px; padding: 12px; border: 1px solid #d2d2d7; border-radius: 8px; box-sizing: border-box; margin-bottom: 12px; }
            .btn-copy { background: #34c759; }
        </style>
    </head>
    <body>

    <div class="card">
        <h2>⚡ AC表極速辨識系統</h2>
        
        <div class="file-drop-area" onclick="document.getElementById('file-input').click()">
            <span class="upload-icon">📂</span>
            <span id="file-label" style="font-size: 16px; color: #0071e3; font-weight: bold;">選取 AC 表照片</span>
            <input type="file" id="file-input" multiple accept="image/*" onchange="updateFileLabel()">
        </div>

        <button id="upload-btn" class="btn" onclick="startBatchAnalyze()" disabled>開始極速分析並排序</button>
        
        <div id="progress-box" class="progress-box">
            <div class="spinner"></div>
            <div id="progress-text" style="color: #666; font-weight: bold;">付費通道全速分析中，請稍候...</div>
        </div>

        <div id="error-box" class="error-msg"></div>

        <div id="result-box" class="result-area">
            <h3 style="margin-bottom: 10px; color: #1d1d1f;">📋 辨識結果（依機台號由小到大排序）：</h3>
            <textarea id="result-text" readonly></textarea>
            <button class="btn btn-copy" onclick="copyToClipboard()">📋 複製全部數據</button>
        </div>
    </div>

    <script>
        function updateFileLabel() {
            const input = document.getElementById('file-input');
            const label = document.getElementById('file-label');
            const btn = document.getElementById('upload-btn');
            
            if (input.files.length > 0) {
                label.innerText = `已成功載入 ${input.files.length} 張照片`;
                btn.disabled = false;
            } else {
                label.innerText = "選取 AC 表照片";
                btn.disabled = true;
            }
        }

        async function startBatchAnalyze() {
            const input = document.getElementById('file-input');
            if (input.files.length === 0) return;

            const btn = document.getElementById('upload-btn');
            const progressBox = document.getElementById('progress-box');
            const resultBox = document.getElementById('result-box');
            const errorBox = document.getElementById('error-box');

            btn.disabled = true;
            progressBox.style.display = 'block';
            errorBox.style.display = 'none';
            resultBox.style.display = 'none';

            const formData = new FormData();
            for (let i = 0; i < input.files.length; i++) {
                formData.append('files', input.files[i]);
            }

            try {
                const response = await fetch('/api/batch-analyze', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                progressBox.style.display = 'none';
                btn.disabled = false;

                if (data.status === 'success') {
                    document.getElementById('result-text').value = data.formatted_text;
                    resultBox.style.display = 'block';
                    if (data.errors && data.errors.length > 0) {
                        errorBox.innerText = '⚠️ 部分照片辨識失敗：\\n' + data.errors.join('\\n');
                        errorBox.style.display = 'block';
                    }
                } else {
                    errorBox.innerText = '❌ 系統異常：' + data.message;
                    errorBox.style.display = 'block';
                }
            } catch (error) {
                progressBox.style.display = 'none';
                btn.disabled = false;
                errorBox.innerText = '❌ 傳輸超時或網路中斷，請確認網路環境。';
                errorBox.style.display = 'block';
            }
        }

        function copyToClipboard() {
            const textarea = document.getElementById('result-text');
            textarea.select();
            document.execCommand('copy');
            alert('已成功複製全部數據到剪貼簿！');
        }
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/batch-analyze")
async def batch_analyze(files: List[UploadFile] = File(...)):
    loop = asyncio.get_event_loop()
    semaphore = asyncio.Semaphore(15)

    async def process_file_with_semaphore(file):
        content = await file.read()
        async with semaphore:
            return await loop.run_in_executor(None, process_single_image, content, file.filename)

    tasks = [process_file_with_semaphore(f) for f in files]
    results = await asyncio.gather(*tasks)

    valid_results = [r for r in results if r.get("status") == "success"]
    error_results = [r for r in results if r.get("status") == "error"]

    if not valid_results and error_results:
        return JSONResponse({
            "status": "error",
            "message": f"全數辨識失敗。主要原因：{error_results[0]['message']}"
        })

    valid_results.sort(key=lambda x: x["machine_id"])

    formatted_lines = []
    for item in valid_results:
        formatted_lines.append(f"{item['raw_a']}")
        formatted_lines.append(f"{item['raw_c']}")

    final_text = "\n".join(formatted_lines)
    err_msgs = [f"{e['filename']}: {e['message']}" for e in error_results]

    return JSONResponse({
        "status": "success",
        "total_processed": len(valid_results),
        "formatted_text": final_text,
        "errors": err_msgs
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
