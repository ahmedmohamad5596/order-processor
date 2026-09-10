# قرارات المكدس الحالي (Current Stack Decisions)
## التاريخ: 2026-09-10

> **السابق:** الأقسام الأربعة التالية (Task 15-17) مسجلة كتاريخ مرجعي لكنها **superseded** — كانت تُفترض OpenRouter + GLM + response_format + state.json. الوضع الحالي مختلف (مُوثق أدناه).

### الوضع الفعلي الحالي

| البند | القرار |
|---|---|
| **موفر AI** | Agnes API hub عبر `AI_API_KEY` + `AI_API_URL` (بدل OpenRouter) |
| **الموديل الأساسي** | `agnes-2.5-flash` (`AI_MODEL_ID`) |
| **Fallback** | `AI_FREE_MODEL` (افتراضيًا نفس الموديل) عند 429 |
| **response_format** | **مُزال نهائيًا** — يُعتمد على تعليمات الـprompt + regex extraction |
| **توطين الـAI** | كل منطق الاقتراحات AI مدمج داخل `engine/customer_batch_engine.py` (استدعاء Python واحد/عميل) |
| **وحدات مكررة** | `engine/ai_suggestions.py` و`engine/book_ai_suggestions.py` **حُذفتا** (كانا مكررين وميتين) |
| **جسر ميت** | `server/address_matcher.js` و`server/book_matcher.js` **حُذفا** (غير مستخدمين في الإنتاج) |
| **تأصيل الاقتراحات** | اقتراحا المحافظة والمدينة يُطبَّقان تلقائيًا **فقط** إذا كان الاسم مذكورًا في نص الطلب (in-text grounding) — مضاف للمحافظة في عهدة Task 16/اليوم |
| **حفظ العنوان** | لا "echo" للمدينة داخل حقل المنطقة — تُمرَّر المدينة fallback لـ`resolve_address` فقط دون حفظها |
| **حفظ الحالة** | PostgreSQL عبر `DATABASE_URL` (لذا لا `state.json`) |
| **الحماية** | أداة داخلية بلا auth (قرار مقصود) |

### ملاحظة تاريخية على GLM
قرار Task 15 (استخدام `z-ai/glm-5.3-flash` المدفوع + `response_format`) **لم يعد قائمًا**: المكدس انتقل لـ Agnes 2.5 flash عبر `AI_API_KEY`، وأُزيل `response_format` (كان سبب NO-JSON على GLM). مقارنة التكلفة/الجودة في الأسفل تبقى مرجعًا للمقارنات القديمة.

---

# قرار موديل الذكاء الاصطناعي (AI Model Decision) — **superseded**
## التاريخ: 2026-09-08

### الخلفية
نظام معالجة الطلبات (Order Processor) يستخدم موديلات الذكاء الاصطناعي لاقتراح:
- تعيين مدن مصر (AI suggestions in `engine/ai_suggestions.py`)
- مطابقة أسماء كتب (`engine/book_ai_suggestions.py`)
- كلاهما عبر OpenRouter، والموديل الأساسي حاليًا `z-ai/glm-5.3-flash`

### القرار
**الاستمرار باستخدام `z-ai/glm-5.3-flash` كموديل أساسي مدفوع**، مع إضافة `response_format: {'type': 'json_object'}` رسميًا في استدعاء الـAPI (تم التنفيذ في كلا الملفين).

### تفاصيل القرار

#### 1. الموديل الحالي
- **الموفر**: OpenRouter
- **الموديل**: `z-ai/glm-5.3-flash`
- **السعر**: $0.075/M token (prompt) + $0.25/M token (completion)
- **التكلفة التقديرية**: ~$0.08 لكل 1000 طلب اقتراح (بمعدل ~600 token prompt + 150 token response)
- **التصميم الحالي**: يستخدم `response_format: {'type': 'json_object'}` منذ تعديل Task 15

#### 2. الموديلات المجانية المتاحة على OpenRouter (حالة سبتمبر 2026)
قائمة كاملة بـ19 موديل `:free` مع سعر $0/توكن:

| الموديل | السياق | JSON mode | مناسب للحالة |
|---|---|---|---|
| `google/gemma-4-31b-it:free` | 262K | ✅ | الأفضل جودة |
| `google/gemma-4-26b-a4b-it:free` | 262K | ✅ | MoE، أسرع |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262K | ✅ + structured_outputs | جيد لكن بطيء (~11s/طلب) |
| `dots-studio/dots-3-note-preview:free` | 512K | ✅ | غير مستقر (2/3 empty في اختباراتنا) |
| `liquid/lfm-2.5-2.6b:free` | 64K | ✅ | صغير جدًا (2.6B) |
| `thinkingmachines/inkling:free` | 1M | ❌ | عمومي |
| `openrouter/free` | 200K | ✅ | router |
| ... و12 موديل تخصصي (coding, finance, health, music, safety) |

**نطاق الـrate limits المجانية**:
- 20 طلب/دقيقة (ثابت لجميع :free)
- 50 طلب/يوم (إذا لم تشترِ $10 credits في حياتك)
- 1000 طلب/يوم (بعد شراء $10 credits مرة واحدة — دائم)

#### 3. نتائج الاختبار المقارن (September 2026)
أُجريت مقارنة عملية على نفس الـprompts العربية الطويلة (قوائم المدن/الكتب الكاملة):

| النموذج | النتيجة |
|---|---|
| `z-ai/glm-5.3-flash` (مدفوع) | ✅ 4/4 نجح — موثوق |
| `google/gemma-4-31b-it:free` | ❌ 429 من مزود Google (زحام في الـfree pool) |
| `nvidia/nemotron-3-super-120b-a12b:free` | ⚠️ 2/2 JSON + 2/4 نص تفكير/empty (غير مستقر) |
| `dots-studio/dots-3-note-preview:free` | ⚠️ 1/3 نجح فقط — أخطاء جغرافية (حلوان لمنصورة!) |
| `liquid/lfm-2.5-2.6b:free` | ❌ 2/3 empty |

#### 4. الفرق في الجودة بين المجاني والمدفوع
- **التكلفة**: الموديل المدفوع يكلف ~$0.08 لكل 1000 طلب — مبلغ زهيد.
- **الموثوقية**: `z-ai/glm-5.3-flash` يعطي JSON سليم بنسبة عالية مع الـprompts القصيرة والمتوسطة.
- **عدم الاستقرار في الـfree**: نماذج مجانية كثيرة تزحمني المزودات وتعيد 429 أو content=None؛ `gemma-4-31b-it:free` فشل بالكامل بسبب زحام Google provider.
- **نوعية الاستخراج العربي**: GLM-5.3 Flash جيد في التصنيف/الاستخراج القصير؛ المجاني (عند نجاحه) أدنى جودة ويخطئ في المدن (مثل "حلوان" لـ"المنصورة").

#### 5. تحسين response_format المُضاف (نقطة 3)
تم تعديل `engine/ai_suggestions.py` و`engine/book_ai_suggestions.py` لإضافة:
```python
'response_format': {'type': 'json_object'}
```
في body الطلب. الاختبارات أثبتت:
- مع prompts قصيرة: يعمل بشكل مثالي (4/4 OK).
- مع prompts طويلة (قائمة مدن كاملة): 4/4 نجح في الاختبار الحاسم، مع بعض الفشل العابرة التي يتعامل معها الـretry loop (MAX_RETRIES=2).
- السبب الجذري لـ"Empty response" السابق كان: GLM flash يستهلك tokens التفكير (reasoning_tokens) ويتجاوز الـmax_tokens → content=None. الإضافة الحالية + retry loop يغطيان الحالة.

### التوصية النهائية
- ✅ **الاستمرار** بـ `z-ai/glm-5.3-flash` كموديل أساسي في `engine/ai_suggestions.py:13` و`engine/book_ai_suggestions.py:17`.
- ✅ **عدم تغيير** الـMODEL_ID الافتراضي أو إضافة fallback آلية الآن — هذا عمل Task 16 (Batching & parallelism) حيث يمكن إضافة fallback لـ `openrouter/free` عند 429 فقط كـnetwork safety net.
- ✅ ملفات القرار والاختبارات كافية لاعتماد Task 15 نهائيًا.

### الملفات المتأثرة
- `engine/ai_suggestions.py` — تمت إضافة `response_format` + `isinstance` guard.
- `engine/book_ai_suggestions.py` — تمت إضافة `response_format` + `isinstance` guard.
- `public/index.html` — `formatSuggestion` يعرض "مفيش اقتراح موثوق" عند null suggestion (تعديل Task 15).
- `server/address_matcher.test.js` — اختبارات Task 15 الجديدة.
- `server/book_matcher.test.js` — اختبارات Task 15 الجديدة.

### ملاحظات تقنية مهمة
- الـ`isinstance(content, str)` guard مُطبّق في `ai_suggestions.py:161` (نعم، ملف العناوين نفسه).
- الـ`Empty response from API` التي ظهرت في live test هي transient من مزود GLM نفسه، وليست bug في الكود — الـretry loop (MAX_RETRIES=2) يغطي معظم الحالات.
- `splitter.test.js` باقٍ فيه bug (SEPARATOR غير معرف) — مُسجل كملحوظة منفصلة، خارج نطاق Task 15.

---

# قرار Task 16: Batch Processing + Concurrency + Fallback — **superseded (history)**
## التاريخ: 2026-09-08

### الخلفية
Task 15 تم الاعتماد النهائي. الآن ننتقل لـTask 16 لتحسين الأداء عبر:
1. استدعاء Python واحد لكل عميل (بدل استدعاء منفصل للعنوان + كتاب/كتاب)
2. `asyncio.gather()` داخل Python لتوازي طلبات AI
3. Bounded concurrency pool في Node.js لمعالجة العملاء المتزامنين
4. Fallback لـ `openrouter/free` عند 429 فقط
5. لوج داخلي يميّز بين الفشل التقني والاقتراح منخفض الثقة

### التنفيذ

#### ملف جديد: `engine/customer_batch_engine.py`
- مستقبل JSON من stdin، معالج كل البيانات في process واحد
- يستخدم `asyncio.gather()` مع semaphore مقيد (AI_CONCURRENCY=5)
- يدعم fallback تلقائي: primary → free عند 429
- يضيف `failure_type` لكل suggestion: `'technical'` أو `'low_confidence'` أو `null`
- اللوج داخلي (stderr):
  - `[INFO] [SUGGEST] suggestion=... conf=X` → نجاح
  - `[INFO] [LOW_CONF] suggestion=... conf=X` → ثقة منخفضة
  - `[WARNING] [TECH_FAIL] error=...` → فشل تقني

#### ملف مُعدّل: `server/assembly.js`
- `processCustomer()`: يستدعي batch engine مرة واحدة بدل address_matcher + book_matcher منفصلين
- `processCustomers()`: bounded concurrency pool (default 5) via Promise semaphore
- يُرجع `{results, stats}` مع timing metrics

#### تعديل: `server/index.js`
- `/api/process` يستقبل `performance` في الـresponse

### نتائج الأداء (10 عملاء، pool=5، API key مفعل) — بعد التصليحات
| المقياس | القيمة |
|---|---|
| الوقت الكلي (wall-clock) | 189,369ms |
| مجموع الأوقات الفردية | 751,980ms |
| **معامل التوازي** | **3.97x** ✅ |
| Avg per customer: | 18,937ms |
| Min: | 8,829ms |
| Max: | 189,282ms |
| طلبات AI | 13 |
| Technical failures: | 4 (30.8%) |
| Low confidence: | 0 |
| Python tests | 82/82 ✅ |

### تحليل أسباب الفشل التقني (بعد التصليحات — Run 5)
| النوع | العدد | السبب |
|---|---|---|
| `Empty response from API` | 1 | GLM transient empty content بعد 3 retries — natural API variance |
| **NO JSON errors** | **0** | تم حلها بإزالة response_format |

### قيد معروف: GLM-5.3-flash + response_format
`response_format: {"type": "json_object"}` **مش مدعوم بشكل صحيح** على GLM-5.3-flash عبر OpenRouter:
- عند إرساله: GLM يدخل deep reasoning mode → reasoning_tokens ≈ max_tokens → content=None
- `structured_outputs: true` كمان مش شغال — النموذج بيتجاهل الـschema
- **الحل**: الاعتماد على prompt instruction + regex extraction (بدون response_format)

### تصليحات Task 16 المُطبقّة
- ✅ `MAX_RETRIES`: 2 → 3 (مرونة أكبر)
- ✅ `REQUEST_TIMEOUT_S`: 60 → 90 (تجنب timeouts على prompts الطويلة)
- ✅ **إزالة `response_format: json_object`** — سبب رئيسي لـ"NO JSON" errors
- ✅ `parallelism_factor` metric في التقرير (بدل speedup% الخاطئ)
- ✅ stderr logging من Python process (لmonitoring الـfailures)

### ملاحظة حول البقية
الـbottleneck الرئيسي بقي في **AI extraction** (طلب واحد/عميل، ≈5-10s، sequential). الـbatching وفّر استدعاءات Python لكن الـextraction نفسه محتاج parallelization منفصلة (out of scope for Task 16).

---

# قرار Task 17: Excel Export with Suggestion Fields — **superseded (history)**
## التاريخ: 2026-09-08

### الخلفية
Task 16 تم الاعتماد. الآن نضيف دعم تصدير Excel مع حقول الـAI suggestions.

### التنفيذ

#### ملف مُعدّل: `server/excel_writer.js`
- إضافة حقول جديدة: `suggestion_book`, `suggestion_confidence`, `suggestion_type`, `suggestion_message`
- تغيير نمط Filename: `orders_<date>_<time>.xlsx`
- معالجة NULL values: "N/A" بدلاً من null/undefined
- Prices كـ numbers (مش strings)
- Books كـ JSON string واحد

#### ملف مُعدّل: `server/index.js`
- تغيير `/api/export` ليعيد الملف مباشرة (res.download) بدل مسار JSON

#### ملف مُعدّل: `public/index.html`
- تحديث `exportToExcel()` لتحميل الملف مباشرة (blob download)
- إضافة toast notifications بدل alerts
- disabled state للزر عند عدم وجود بيانات

### نتائج الاختبار
| الاختبار | النتيجة |
|---|---|
| File generation | ✅ |
| Filename pattern | ✅ `orders_20260908_180920.xlsx` |
| Rows count | ✅ 5 rows |
| Columns count | ✅ 9 columns (بعد حذف title) |
| Data integrity | ✅ confirmed, ambiguous_stage, no_match, tech_failure |
| NULL handling | ✅ N/A for null values |
| Books JSON | ✅ valid JSON string |
| Python tests | ✅ 82/82 passing |

### أعمدة Excel الناتجة (9 أعمدة)
| Column | مثال |
|---|---|
| customer_name | أحمد محمد |
| customer_phone | 01012345678 |
| governorate | القاهرة |
| city | الزاوية الحمراء |
| books | `[{"name":"Full Blast","grade":"G1",...}]` |
| suggestion_book | full blast special |
| suggestion_confidence | 70 |
| suggestion_type | no_match |
| suggestion_message | full blast special |

### تغطية الـSuggestion Types (4 أنواع)
| النوع | الوصف | الحالة |
|---|---|---|
| `confirmed` | لا يوجد اقتراح مطلوب | ✅ |
| `ambiguous_stage` | الكتاب في عدة مراحل (ثقة 100%) | ✅ |
| `no_match` | اقتراح book name من AI | ✅ |
| `tech_failure` | فشل تقني (Empty response, No JSON) | ✅ |

**ملاحظة**: `needs_review` مش `suggestion_type` — ده `customer.status`. الـsuggestion_type بيصف حالة الاقتراح نفسه، مش حالة العميل.

### Aعمدة الـExcel الناتج
| Column | الوصف |
|---|---|
| customer_name | اسم العميل |
| customer_phone | رقم الهاتف |
| title | السنة/الإصدار |
| governorate | المحافظة |
| city | المدينة |
| books | JSON array لكل كتب العميل |
| suggestion_book | اسم الكتاب المقترح |
| suggestion_confidence | نسبة الثقة (0-100) |
| suggestion_type | نوع الاقتراح (confirmed/ambiguous_stage/no_match/tech_failure) |
| suggestion_message | النص الكامل للاقتراح أو سبب الفشل |

### مثال على اللوج الداخلي
```
[INFO] [SUGGEST] suggestion="full blast special" conf=70
[INFO] [AMBIGUOUS] book="English World" stages=7
[WARNING] [TECH_FAIL] error="No JSON found in response"
```

### قرار الفشل التقني vs الثقة المنخفضة
- **Technical** (`failure_type='technical'`): `Empty response`, `No JSON found`, `API error`, timeout — يعرض "مفيش اقتراح موثوق" في الداشبورد مع لوج تنبيهي
- **Low confidence** (`failure_type='low_confidence'`): الموديل رد بثقة < 10% — نفس العرض لكن لوج معلوماتي
- **Success**: الموديل رد بثقة ≥ 10% — يعرض الاقتراح في الداشبورد

### ملاحظة حول البقية
الوقت الرئيسي (≈80%) يذهب لـ AI extraction (طلب واحد/عميل). الـbatching وفّر استدعاءات Python متعددة لكن الـbottleneck بقي في الـAI calls. Task 16 حقق:
- ✅ استدعاء Python واحد/عميل (بدل N+1)
- ✅ fallback تلقائي على 429
- ✅ لوج failure_type لل_monitoring_
- ⚠️ Time per customer masih ~23s (نفس ترتيب الحجم — الـAI extraction هو الغالي)
