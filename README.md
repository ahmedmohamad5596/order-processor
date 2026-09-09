# Order Processor - نظام معالجة الطلبات

## نظرة عامة

نظام متكامل لمعالجة طلبات الكتب المدرسية باللغة الإنجليزية، مع:microsoft:

- **استخراج ذكي** للبيانات باستخدام AI (OpenRouter)
- **مطابقة عناوين** مصرية (محافظات، مدن، areas)
- **مطابقة كتب** مع قائمة أسعار معتمدة
- **اقتراحات AI** للبيانات المفقودة أو غير الواضحة
- **تصدير Excel** بتنسيق J&T Express
- **واجهة dashboard** تفاعلية

## المتطلبات

- Python 3.10+
- Node.js 18+
- OpenRouter API Key

## التثبيت

```bash
# تثبيت dependencies للـPython
pip install -r requirements.txt

# تثبيت dependencies للـNode
npm install
```

## التشغيل

```bash
# إعداد متغير البيئة
$env:OPENROUTER_API_KEY = "sk-or-v1-..."

# تشغيل السيرفر
npm start
```

## واجهة API

| Endpoint | الوصف |
|---|---|
| `GET /health` | صحة السيرفر |
| `GET /api/metrics` | إحصائيات الأداء |
| `GET /api/logs` | سجلات النظام |
| `POST /api/process` | معالجة طلب جديد |
| `POST /api/export` | تصدير Excel |
| `GET /api/state` | تحميل الحالة المحفوظة |
| `POST /api/save` | حفظ الحالة يدوياً |
| `DELETE /api/state` | مسح الحالة |
| `GET /api/models` | معلومات الموديلات |

## البنية

```
├── engine/              # Python engines
│   ├── book_matcher.py  # مطابقة الكتب
│   ├── matcher.py       # مطابقة العناوين
│   ├── normalizer.py    # تطبيع النصوص
│   └── ...
├── server/              # Node.js server
│   ├── assembly.js      # تجميع النتائج
│   ├── excel_writer.js  # تصدير Excel
│   ├── state_store.js   # حفظ الحالة
│   └── logger.js        # logging
├── public/              # Frontend dashboard
│   └── index.html
└── data/                # بيانات مؤقتة
    ├── lookup_cache.json
    └── areas_learned.json
```

## الاختبارات

```bash
# Python tests
python -m pytest tests/ -q

# JS tests
node server/splitter.test.js
node server/address_matcher.test.js
node server/book_matcher.test.js
```

## ملاحظات مهمة

- **الـNormalization**: لا يتم تحويل `ى` إلى `ي` للحفاظ على كلمات مثل "ابتدائي"
- **AI Model**: `z-ai/glm-5.3-flash` عبر OpenRouter
- **Free Fallback**: عند 429، يتم الانتقال لـ `openrouter/free`
- **State Persistence**: يتم حفظ الحالة تلقائياً في `state.json`

## الـBug Fixes (Task 18)

تم إصلاح:
1. توسيع المراحل المتعددة (multi-grade expansion)
2. تطبيع "تانية" → "تانيه" للـgrade detection
3. إزالة تحويل `ئ` → `ي` الذي كان يكسر "ابتدائي"
4. إضافة "جسر السويس" لجدول الـareas
5. validation لمنع العملاء الفارغين من الـconfirmed
