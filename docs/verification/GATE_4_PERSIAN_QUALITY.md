# Gate 4 Persian Editorial Quality

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
