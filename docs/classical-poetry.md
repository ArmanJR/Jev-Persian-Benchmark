# Classical Persian poetry: meaning and application

Jev correctly identified the intended meaning and matched a modern situation for
**all 24 excerpts** in this pilot. Situation-matching accuracy was **100% with the
verse and 25% without it**. These results support using the passage to choose a
matching situation on this set, not comprehensive mastery of classical poetry.

## Recorded full run

- Model: **`jev-1.13.0`**, using **`typesafe-sdk==0.7.1`**.
- Dataset: **`classical_transfer`, revision `1.0.0`**; six excerpts each from
  Sa’adi, Hafez, Rumi, and Ferdowsi.
- Started: **2026-09-26 01:42:39 UTC**.
- Completion: **96/96 requests and responses valid**, with no request failures,
  response-validation failures, unfinished questions, or model mismatches.

| Test | Correct / evaluated | Accuracy |
|---|---:|---:|
| Choose a modern-Persian paraphrase of the verse | 24/24 | 100% |
| Choose a modern situation illustrating the verse | 24/24 | 100% |
| Both main tasks correct for the same excerpt | 24/24 excerpts | 100% |
| Situation matching with the authored prose meaning instead | 24/24 | 100% |
| Situation matching with no passage | 6/24 | 25% |

The two main tasks account for **48 questions**. The other **48 are controls**,
reported separately rather than added to main accuracy. Each full main task has
six correct answers per label A–D, so uniform guessing and always choosing one
label both have a 25% baseline. The paired-excerpt result is not an additional test.

Choice Brier scores were **0.0006 for paraphrase** and **0.0285 for application**
(lower is better; range 0–2). Returned confidence was at least 0.8 for 24/24
paraphrases and 19/24 applications; all of those selections were correct.
Confidence is a model output, not a guarantee of correctness.

The full run used **63,129 input tokens and 4,824 output tokens**. Total request
time was **12.65 seconds**, with a **122 ms median**, including transport handling
and any SDK retries. Local artifacts are in `results/classical-full-v1/`:
`run.json`, `requests.jsonl`, `answers.jsonl`, `summary.json`, and `report.md`.
These raw run files are Git-ignored; the results and examples here are recorded
from that saved run.

## What Jev actually received

Each question was a separate, stateless Choice request containing the original
verse, a Persian instruction, and four candidate answers. Jev selected an option;
it was not asked to write a poem, produce an explanation, or identify the poet.

The application request did **not** receive the paraphrase question, its answer,
or the benchmark rationale. Poet names, source links, keys, and rationales shown
below are documentation for readers, not additional hints sent to Jev. The
explanations below describe the benchmark's intended distinctions; they are **not
Jev-generated reasoning**.

The first two examples reproduce all main-question choices in their submitted
A–D order. The following examples show selected answers and explain how the same
choices can test different meanings. Full inputs are in
[scenarios.jsonl](../data/classical/scenarios.jsonl), with keys and rationales in
[gold.jsonl](../data/classical/gold.jsonl).

## Example 1: Hafez — overlooking what one already has

Excerpt `c010`, from [Hafez, ghazal 143](https://ganjoor.net/hafez/ghazal/sh143):

> سال‌ها دل طلبِ جامِ جم از ما می‌کرد  
> وآنچه خود داشت ز بیگانه تمنّا می‌کرد

### Paraphrase — `c010pq1`

کدام عبارت، معنای اصلی متن داده‌شده را بهتر بیان می‌کند؟

- **A:** آدمی هرچه بیشتر جست‌وجو کند، نیازش به شناخت خود کمتر می‌شود.
- **B:** برای رسیدن به هر خواسته‌ای باید داشته‌های خود را کنار بگذاریم.
- **C:** هرچه دیگران دارند از داشته‌های ما ارزشمندتر و سودمندتر است.
- **D:** گاه از داشته خود غافلیم و همان را از دیگران طلب می‌کنیم.

**Expected: D. Jev selected: D — correct.**

The target is the contrast between already possessing something and seeking it
elsewhere without recognizing that possession. The item does not require one
exhaustive mystical interpretation of the cup of Jamshid.

### Situation matching — `c010aq1`

In a new request, Jev received the same verse and this question:

کدام موقعیت، پیام اصلی متن داده‌شده را بهتر نشان می‌دهد؟

- **A:** کسی بدون بررسی پیامدها تعهدی را می‌پذیرد و بعد که گرفتاری‌های آن آشکار می‌شود، از تصمیم شتاب‌زده‌اش پشیمان می‌شود.
- **B:** کارآموزی با حضور مداوم در کنار همکاران دقیق، کم‌کم همان دقت و نظم را در کار خودش پیدا می‌کند.
- **C:** گروهی مدت‌ها دنبال مشاوری بیرون از مجموعه می‌گردد، بی‌خبر از اینکه تخصص لازم از قبل در میان اعضای خودش وجود دارد.
- **D:** تماشاگری که هیچ‌گاه شرایط امداد در بحران را تجربه نکرده، از جای امن خود دشواری کار امدادگران را ناچیز می‌پندارد.

**Expected: C. Jev selected: C — correct.**

The modern situation preserves the relation between an overlooked internal
resource and an unnecessary external search. The alternatives concern regret,
influence through companionship, and an outsider's limited understanding.

## Example 2: Rumi — projecting one's assumptions onto someone else

Excerpt `c013`, from [the opening of Rumi's Masnavi](https://ganjoor.net/moulavi/masnavi/daftar1/sh1):

> هر کسی از ظَنّ خود شد یار من  
> از درون من نجُست اَسرار من

### Paraphrase — `c013pq1`

کدام عبارت، معنای اصلی متن داده‌شده را بهتر بیان می‌کند؟

- **A:** هرکس به من نزدیک شد، به کمک گمان خود حقیقت درونم را کاملاً شناخت.
- **B:** برای شناختن هر فرد، تصور اولیه ما کافی است و نیازی به پرسیدن نیست.
- **C:** دیگران برداشت خود را به من نسبت دادند، بی‌آنکه حقیقت درونم را بشناسند.
- **D:** من عمداً برای هر همراه، شخصیتی متفاوت ساختم تا هیچ‌کس مرا نشناسد.

**Expected: C. Jev selected: C — correct.**

The speaker criticizes others' assumptions in place of inquiry. This is different
from successful understanding through intuition or deliberate deception by the
speaker.

### Situation matching — `c013aq1`

کدام موقعیت، پیام اصلی متن داده‌شده را بهتر نشان می‌دهد؟

- **A:** فردی با هر افزایش دارایی، خواسته بزرگ‌تری پیدا می‌کند؛ هرچه بیشتر به دست می‌آورد، باز احساس می‌کند هیچ‌چیز برایش کافی نیست.
- **B:** شنوندگان یک سخن، هرکدام تجربه و پیش‌فرض شخصی خود را به گوینده نسبت می‌دهند، بی‌آنکه منظور واقعی او را پرس‌وجو کنند.
- **C:** دو واحد سازمان از بخش‌های متفاوت یک گزارش نتیجه‌های ناسازگار می‌گیرند؛ با دیدن گزارش کامل، منشأ اختلافشان روشن می‌شود.
- **D:** فردی به جای اندوهگین شدن از اتفاق بدی که هنوز رخ نداده، آرامش امروز را حفظ می‌کند و منتظر روشن شدن وضعیت می‌ماند.

**Expected: B. Jev selected: B — correct.**

Both B and C involve incomplete understanding, but B specifically captures
listeners imposing personal assumptions on a speaker. C instead concerns
different observers receiving different parts of the evidence.

### The controls on this same question

For the prose control, the verse was replaced by this exact authored meaning:

> دیگران از روی گمان‌ها و پیش‌فرض‌های خود با من همراه شدند، اما برای شناختن حقیقت درونی و منظور من جست‌وجو نکردند.

For the no-poem control, it was replaced by:

> متن در این آزمون ارائه نشده است.

The application instruction, all four situations, their ordering, and the expected
answer **B** stayed unchanged. Each condition was a fresh request, with its own ID.

| Condition | Question ID | Jev selected | Result against the original key |
|---|---|---|---|
| Original verse | `c013aq1` | B | Correct |
| Authored prose meaning | `c013cq1` | B | Correct |
| No passage | `c013nq1` | D | Incorrect |

With no passage, the question is intentionally missing the information needed to
justify a unique match. Its score measures how often choices alone recover the
original key; it is not ordinary reading-comprehension accuracy. This individual
example illustrates the control, while the aggregate result is 6/24, not zero.

## Additional examples: timing and consequences

These show the verses and selected correct options, rather than repeating every
distractor.

### Sa’adi — knowing when to speak

Excerpt `c006`, from [the preface to the Golestan](https://ganjoor.net/saadi/golestan/dibache):

> اگر چه پیشِ خردمند خامُشی ادب است  
> به وقتِ مصلحت آن به، که در سخن کوشی  
> دو چیز طَیرهٔ عقل است، دم فرو بستن  
> به وقتِ گفتن و گفتن به وقتِ خاموشی

For paraphrase `c006pq1`, both the expected answer and Jev's selection were **D**:
«خردمندی در تشخیص زمان مناسب سخن گفتن و زمان مناسب سکوت است.»

For application `c006aq1`, both were **B**:
«عضو جلسه هنگام توضیح دیگران گوش می‌دهد و وقتی تصمیمی نیاز به اصلاح دارد، در فرصت مناسب نظرش را مطرح می‌کند.»

This tests conditional advice, not an unconditional preference for silence or
talking. The other situations concerned compassion, choosing safety over a risky
opportunity, and acquiring a skill through learning.

### Ferdowsi — regretting an unconsidered action

Excerpt `c020`, from [the Shahnameh's praise of wisdom](https://ganjoor.net/ferdousi/shahname/aghaz/sh2):

> کسی کو خِرَد را نَدارَد زِ پیش  
> دِلش گَردَد از کَردهٔ خویش ریش

For paraphrase `c020pq1`, both the expected answer and Jev's selection were **B**:
«عمل کردن بی‌راهنمایی خرد، می‌تواند انسان را از کرده خود پشیمان و آزرده کند.»

Application `c020aq1` used the **exact same A–D situations as the Hafez example**,
but both the expected answer and Jev's selection were now **A**:
«کسی بدون بررسی پیامدها تعهدی را می‌پذیرد و بعد که گرفتاری‌های آن آشکار می‌شود، از تصمیم شتاب‌زده‌اش پشیمان می‌شود.»

Choosing the consultant situation C for both poems would be wrong here. Across
the dataset, each four-situation bank serves four excerpts with different correct
answers, so a generic preference for one situation cannot solve the whole bank.

## What the results support—and what they do not

On these selected passages, Jev succeeded at identifying a main message,
distinguishing alternative meanings, and recognizing a corresponding modern
situation. Removing the passage reduced application accuracy by **75 percentage
points**, consistent with using information from the poem.

Original verse and supplied prose meaning both produced perfect application
accuracy. There was no observed accuracy disadvantage from poetic wording on
this set, but a small test with perfect scores cannot establish equal difficulty
or locate the model's limits. The examples do not reveal Jev's internal reasoning.

This is an **assistant-authored, assistant-reviewed pilot without independent
human annotation**. Passages are deliberately selected, often familiar and
didactic; some share a source section or related themes. Six excerpts per poet
do not establish representative per-poet ability. Source checking verifies wording
and attribution, not the correctness of an authored interpretation. Shared author
framing, memorization, and lexical cues are not ruled out by the controls.

The task does not establish reliable interpretation of whole poems, competing
mystical readings, or subtle ambiguity. Independent literary review and broader,
harder examples are needed before making those claims.

For source provenance, frozen-data rules, and reproduction commands, see the
[dataset review and protocol](../data/classical/REVIEW.md). The eight-question
smoke set is a subset and is not added to any full-run score above.
