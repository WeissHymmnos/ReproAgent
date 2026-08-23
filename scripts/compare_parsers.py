"""对比项目解析(Markdown+截图)与纯图片视觉解析的效果。"""

import time
from pathlib import Path

from reproagent.ingestion.uploader import upload_pdf
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.parser.report_parser import ReportParser
from reproagent.settings import Settings

# 选择一份样本研报进行对比测试
PDF_PATH = Path(
    "/home/wh/Documents/KnowledgeBase/Quant/WH/华泰系列研报/华泰因子系列"
    "/估值因子/华泰多因子系列2：单因子测试之估值类因子.pdf"
)


def run_comparison():
    print(f"Starting comparison on {PDF_PATH.name}...")
    
    # 1. 初始化 Settings
    # 自动读取 .env (包括 LLM_API_KEY, LLM_PROVIDER, LLM_MODEL)
    settings = Settings(data_source="local")
    
    # 2. Ingestion
    report = upload_pdf(PDF_PATH)
    
    # 3. 方法A：项目现有的混合解析 (Markdown文本 + 截图)
    print("\n--- Method A: Markdown Text + Images (Current Pipeline) ---")
    start_a = time.time()
    parser = ReportParser(settings)
    # 这步会走 layout_extractor (Finpdfpro / PyMuPDF) 抽取 Markdown
    # 然后交给 llm_extractor (带上截图)
    specs_a = parser.parse(report)
    time_a = time.time() - start_a
    
    print(f"Method A completed in {time_a:.2f} seconds. Found {len(specs_a)} factors.")
    for i, spec in enumerate(specs_a):
        print(f"  [{i+1}] {spec.factor_name} / {spec.factor_name_cn}")
        print(f"      Formula: {spec.formula}")
    
    # 4. 方法B：直接转图片视觉解析 (纯 Vision)
    print("\n--- Method B: Direct Vision Only (No Markdown Text) ---")
    start_b = time.time()
    extractor = LLMExtractor(settings)
    # 传入空的 Markdown，强迫模型完全依赖附加的 base64 PDF 截图进行提取
    specs_b = extractor.extract(report, markdown="")
    time_b = time.time() - start_b
    
    print(f"Method B completed in {time_b:.2f} seconds. Found {len(specs_b)} factors.")
    for i, spec in enumerate(specs_b):
        print(f"  [{i+1}] {spec.factor_name} / {spec.factor_name_cn}")
        print(f"      Formula: {spec.formula}")
        
    print("\n--- Comparison Summary ---")
    if not settings.llm_api_key.get_secret_value():
        print("⚠️ WARNING: No LLM API Key was found in `.env` or environment variables.")
        print("Both methods fell back to the local Mock Factor (mock_momentum).")
        print("To see a real comparison, please configure `LLM_API_KEY` in the `.env` file.")
    else:
        print("Comparison completed successfully using GPT-4o.")


if __name__ == "__main__":
    run_comparison()
