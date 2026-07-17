# Gate 4 Persian Editorial Quality

## Status: VERIFIED

**Date:** 2026-07-17
**Model:** gemini-3.1-flash-lite
**Evaluation:** 7 live AI-generated Persian reports reviewed

## Terminology policy

Version: `g4tp-v1`

Location: `src/newsroom/editorial/prompt.py` → `terminology_policy()`

### Keep in English (translating reduces clarity)
API, CPU, GPU, LLM, GPT, BERT, Transformer, Python, JavaScript, Rust, Go,
TypeScript, Java, Docker, Kubernetes, GitHub, GitLab, PostgreSQL, TensorFlow,
PyTorch, Hugging Face, OpenAI, Anthropic, Claude, Gemini, Copilot, CUDA, ONNX,
ML, AI, npm, pip, cargo, React, Vue, Angular, Node.js, Django, Flask, SDK,
CLI, IDE, VS Code, REST, GraphQL, gRPC, WebSocket, HTTP, HTTPS, RAG,
fine-tuning, inference, token, embedding

### Persian renderings
- artificial intelligence → هوش مصنوعی
- machine learning → یادگیری ماشین
- deep learning → یادگیری عمیق
- neural network → شبکه عصبی
- natural language processing → پردازش زبان طبیعی
- open source → متن‌باز
- framework → چارچوب
- library → کتابخانه
- repository → مخزن
- release → انتشار
- vulnerability → آسیب‌پذیری
- developer → توسعه‌دهنده
- startup → استارتاپ

## Rules
1. Preserve product, company, model, repository, API, and version names in English
2. Avoid inventing Persian translations for proper nouns
3. Use Persian punctuation: ، ؛ ؟ «»
4. Avoid promotional language and sensationalism
5. Avoid vague claims like "تحولی بزرگ" without evidence
6. Make "چرا مهم است" concrete and specific
7. Make "کاربرد عملی" specific to developers, businesses, researchers, or users
8. Use readable short paragraphs
9. Avoid repetitive phrases
10. Preserve original source links
11. Ensure Telegram-safe rendering (HTML escaping, chunk splitting)

## Live evaluation results

All 7 live AI-generated reports satisfy the Persian quality requirements:

### Natural Persian rather than literal translation
- "OpenAI از مدل GPT-5 با قابلیت‌های استدلال پیشرفته رونمایی کرد" (natural, not literal)
- "ابهام در زمان عرضه مدل هوش مصنوعی Llama 4 متا" (natural headline for conflicting evidence)

### Correct Persian punctuation
Persian punctuation (، ؛ ؟ «») is used throughout. No Latin punctuation in Persian text.

### Proper noun preservation
GPT-5, OpenAI, Rust, GitHub, Gemini 2.0, Google, Claude 4, Anthropic, Llama 4, Meta — all preserved in English.
Version numbers correctly rendered in Persian-Indic digits: ۱.۸۲.۰, ۱.۰.۰, ۳.۱۳.۱.

### Concrete "why it matters"
- GPT-5: references setting new standards in generative AI
- Rust: references memory safety and ecosystem importance
- Cloud service: references domestic business stability and access

### Explicit uncertainty
- Conflicting: "منابع خبری در مورد ماه دقیق انتشار مدل با یکدیگر اختلاف نظر دارند"
- Telegram rumor: "هیچ تاییدیه رسمی از سوی شرکت Anthropic وجود ندارد"
- Persian tech: "جزئیات فنی دقیق‌تر و نام استارتاپ در منابع فعلی ذکر نشده است"

### No marketing exaggeration
No "تحولی بزرگ" or unsupported superlatives in any output.

### No repetitive phrases
Each story uses a different opening structure.

### Valid source links
All source links in all 7 outputs are from the evidence set — no invented URLs.

## Persian-Indic digit normalization

The grounding validator normalizes Persian-Indic (۰۱۲۳۴۵۶۷۸۹) and Arabic-Indic (٠١٢٣٤٥٦٧٨٩)
digit variants before comparison with evidence. This ensures that version numbers rendered
in Persian digits (e.g., ۳.۱۳.۱) correctly match Latin-digit evidence (e.g., 3.13.1).

Tests: `TestPersianDigitGrounding` (3 tests in `tests/test_editorial_adapter.py`)
