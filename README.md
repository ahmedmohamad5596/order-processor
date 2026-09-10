# Order Processor - نظام معالجة الطلبات

## نظرة عامة

نظام متكامل لمعالجة طلبات كتب اللغة الإنجليزية من النصوص الخام:

- **استخراج ذكي** للبيانات (اسم، هواتف، عنوان، كتب) عبر AI
- **مطابقة عناوين** مصرية كاملة (محافظات، مدن، مناطق/أحياء/شوارع/كمبوندات/قرى)
- **مطابقة كتب** مع قائمة أسعار معتمدة (`book_prices.xlsx`)
- **اقتراحات AI** للبيانات المفقودة أو غير الواضحة (محكومة بنص الطلب — لا اختيار من لا شيء)
- **تصدير Excel** بتنسيق J&T Express
- **واجهة dashboard** تفاعلية مع تحقق تلقائي للعناوين

## المتطلبات

- Python 3.10+
- Node.js 18+
- AI API Key (Agnes API hub)
- PostgreSQL (على Railway يتم ربطه تلقائياً عبر `DATABASE_URL`)

## التثبيت

```bash
# تثبيت dependencies للـPython
pip install -r requirements.txt

# تثبيت dependencies للـNode
npm install
```

## التشغيل

```bash
# إعداد متغيرات البيئة (انسخ .env.example إلى .env)
$env:AI_API_KEY = "your-key"

# تشغيل السيرفر محلياً
npm run dev
```

## واجهة API

| Endpoint | الوصف |
|---|---|
| `GET /health` | صحة السيرفر |
| `GET /api/metrics` | إحصائيات الأداء |
| `GET /api/logs` | سجلات النظام |
| `POST /api/process` | معالجة طلب جديد |
| `GET/POST /api/export` | تصدير Excel |
| `GET /api/state` | تحميل الحالة المحفوظة |
| `POST /api/save` | حفظ الحالة يدوياً |
| `DELETE /api/state` | مسح الحالة |
| `PUT /api/customer/:id` | تعديل عميل |
| `POST /api/customer/:id/re-extract` | إعادة الاستخراج من نص معدل |
| `POST /api/customer/:id/reject` | رفض طلب |
| `DELETE /api/customer/:id` | حذف عميل |
| `POST /api/customers/delete` | حذف جماعي |
| `POST /api/customers/delete-all` | حذف الكل |
| `GET /api/geo/governorates` | المحافظات |
| `GET /api/geo/cities` | مدن محافظة |
| `GET /api/geo/search` | بحث شامل في المرجع الجغرافي |
| `GET /api/books/catalog` | كتالوج الكتب |
| `GET /api/models` | معلومات الموديلات |

## البنية

```
├── engine/                # Python engines
│   ├── customer_batch_engine.py  # المعالجة الشاملة (عنوان + كتب + اقتراحات AI)
│   ├── book_matcher.py          # مطابقة الكتب
│   ├── book_lookup_builder.py   # قائمة أسعار الكتب
│   ├── matcher.py               # مطابقة العناوين
│   ├── save_address.py          # حفظ العناوين + بناء المعرفة
│   ├── geo_search.py            # بحث واجهة التحقق التلقائي
│   ├── normalizer.py            # تطبيع النصوص
│   ├── lookup_builder.py        # بناء مرجع المحافظات/المراكز
│   └── ...
├── server/                # Node.js server
│   ├── index.js           # Express + endpoints
│   ├── assembly.js        # تجميع النتائج عبر engine
│   ├── excel_writer.js    # تصدير Excel
│   ├── state_store.js     # حفظ الحالة في PostgreSQL
│   ├── geo_reference.js   # الجسر الحالي للمرجع الجغرافي (python)
│   └── logger.js          # logging
├── public/                # Frontend dashboard
│   └── index.html
└── data/                  # بيانات
    ├── egypt_governorates.xlsx  # مرجع المحافظات/المراكز/المناطق
    ├── book_prices.xlsx         # قائمة الأسعار
    ├── areas_learned.json       # مناطق متعلمة من الطلبات
    └── address_knowledge.json   # معرفة العناوين (runtime)
```

## الاختبارات

```bash
# Python tests (196 test)
python -m pytest tests/ -q

# JS checks
node --check server/*.js

# Node module tests
node server/splitter.test.js
node server/excel_writer.test.js
node server/phone_validator.test.js
node server/assembly.test.js
```

## ملاحظات مهمة

- **الـNormalization**: لا يتم تحويل `ى` إلى `ي` للحفاظ على كلمات مثل "ابتدائي"
- **AI Model**: `agnes-2.5-flash` عبر Agnes API hub (`AI_API_KEY`)
- **Free Fallback**: عند 429، يتم الانتقال لـ `AI_FREE_MODEL` إن كان محدداً
- **State Persistence**: الحالة محفوظة في PostgreSQL (`DATABASE_URL`)
- **الحماية من الخيال**: اقتراحات AI للمحافظة/المدينة تُطبَّق تلقائياً فقط إذا كان الاسم مذكوراً فعلياً في نص الطلب (in-text grounding)
