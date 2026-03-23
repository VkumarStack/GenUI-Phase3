# Me 

Let's do some brainstorming - no creating code right now. I am working on a multi-phase project that involves creating a benchmark and the automatic evaluation of said benchmark of n to n + 1 UI revisions for large language models. A 0 to n UI change is one where the LLM creates the initially described UI in essentially one go, and there are already plenty of benchmarks on this type of task. In reality, though, a UI is going to be change whether it be due to new requests or due to issues in the existing UI that may have been created in the 0 to n step. As an example, an n to n + 1 revision might be "Make this form element show the required asterisk". 

Some previous phases of this project (which I am not tasked to work on) involve gathering initial UI screens (their code) and asking actual UI designers to provide revision tasks. When LLMs then revise the UI based on the task, the UI designer will give a pass / fail score based on some criteria. This phase will be used to generate a set of revision tasks (from the UIX designers) to act as the benchmark. 

My task involves constructing a system that performs the pipeline automatically (that is, without UI designers). Let's say we have a set of pre-generated initial screens: both the code associated with the UI as well as the rendered image of the UI are available. We also have a set of pre-generated revision tasks (assume that the previous phase successfully trained and LLM to create a large set of these revision tasks based on training from the revisions provided by UIX designers). The LLMs being benchmarked will create the n + 1 revisions based on these tasks, but now it is necessary to create a system that will automatically evaluate these tasks and give a pass / fail score as well as some criteria as to why. Previously, this was done by UIX designers but now this benchmark evaluation must be automatic so some sort of model needs to be created / fine tuned to fulfill their role. Let's assume we have the pass / fail scores and criteria provided by the UIX designers from the previous phase to work as potential training data.

I would like to know some initial ideas on how to approach this. I have some experience working with LLMs, but not Vision Language Models. I also have not fine tuned large models before, though I understand the concepts. 

Questions:
1) Are current SOTA VLMs capable of inspecting UI renders (images) to gauge whether visual changes have occurred? We can assume that the UI tasks are not too complex - that is, we do not have to deal with behavior that might involve interaction like clicking or hovering or of the sort, but rather static vision changes.

 2) How could fine-tuning be leveraged in this task, if it is even needed? I know for fine-tuning a language model, the process involves providing the new text corpus to be used for training. This task, however, involves some logic based on visual data (images)? I think pairing the responses of UIX designers with the images they are critiquing could help but I am not too sure about the specific details here.

3) Which VLMs are available to be fine-tuned in the first place (i.e. not proprietary?). This is a university project, so I may have access to some set of resources to work with possibly large models - though obviously not too large since this is a master's project and not PhD so not too much budget

# Claude
These are great questions and this is a well-scoped problem. Let me work through each one.

---

## 1. Can SOTA VLMs evaluate static visual UI changes?

Yes, and this is probably the most encouraging part of your project. Current SOTA VLMs (GPT-4o, Gemini 1.5 Pro, Claude 3.5 Sonnet, etc.) are surprisingly capable at this kind of task *out of the box*, especially for static visual diffs. A few considerations:

**What they're good at:**
- Detecting presence/absence of elements ("does this form field have an asterisk?")
- Layout comparisons ("is this button now left-aligned vs. centered?")
- Color, typography, and spacing changes
- Component-level inspection ("is this input marked as disabled?")

**Where they struggle:**
- Subtle pixel-level differences (e.g. padding changed by 4px) — though for pass/fail this may not matter
- Hallucinating changes that didn't happen, or missing changes, especially when images are similar
- Ambiguous criteria ("does this look professional?") without grounding

**A useful trick:** Rather than just giving the model the two images, you can also give it the *code* (before and after) alongside the images. VLMs can reason over both modalities simultaneously, and the code acts as a ground truth anchor for what *should* have changed. Since you have the code available, this is a significant advantage over a pure vision-only approach.

---

## 2. How would fine-tuning work for this task?

This is the crux of the project and worth thinking through carefully. There are actually a few distinct strategies, and they're not mutually exclusive.

### Strategy A: Prompt Engineering / Zero-shot/Few-shot (no fine-tuning)
Before you fine-tune anything, you should establish a baseline using a capable closed-source VLM (GPT-4o or Gemini) with a well-crafted prompt. Your prompt would include:
- The original UI image (and/or code)
- The revision task description
- The revised UI image (and/or code)
- A structured rubric asking for pass/fail + reasoning

This baseline might be surprisingly competitive, and it gives you a ceiling to compare against. If it's already hitting 85%+ agreement with UIX designers, fine-tuning may only be needed to reduce cost/latency or for deployment on an open model.

### Strategy B: Fine-tuning an open VLM
For VLM fine-tuning, your training data format is fundamentally the same as LLM fine-tuning, just with images included in the input. A typical training example would look like:

```
Input:
  - Image 1: original UI render
  - Image 2: revised UI render
  - Text: "Revision task: Make the email field show a required asterisk."
  - (optionally) the before/after code

Output:
  - "PASS. The revised UI shows a red asterisk adjacent to the Email label, 
     which was absent in the original. The asterisk is correctly positioned..."
```

Your UIX designer pass/fail scores + written criteria map almost perfectly onto this. Each designer evaluation becomes one supervised fine-tuning (SFT) example. This is called **Visual Instruction Tuning** and is exactly how models like LLaVA were originally trained.

**A key nuance:** The quality of your training signal matters a lot. If UIX designers wrote rich, consistent criteria, those are gold. If the criteria are sparse ("looks good" / "missing the asterisk"), you may want to use a strong closed-source VLM to *expand* those sparse labels into richer reasoning chains before fine-tuning — a technique sometimes called **distillation**.

### Strategy C: DPO / Preference Tuning
If you have cases where multiple designers evaluated the same revision differently, or if you can generate "almost-correct" revisions as negatives, you could go beyond SFT into preference tuning (DPO). This trains the model to prefer the correct reasoning over plausible-but-wrong reasoning. This is more complex and probably a stretch goal for a master's project.

---

## 3. Open VLMs available for fine-tuning

Here's a practical tier list given your resource constraints:

### Tier 1 — Realistic for a master's project (7B–13B range)
| Model | Notes |
|---|---|
| **LLaVA-1.6 / LLaVA-NeXT (7B or 13B)** | The canonical open fine-tunable VLM. Large community, good tooling via LLaVA-Finetune repo. Strong baseline for UI tasks. |
| **Qwen2-VL (7B)** | Alibaba's model, currently one of the strongest open VLMs at this size. Strong OCR and UI understanding. Highly recommended. |
| **InternVL2 (8B)** | Competitive with Qwen2-VL, good at document/UI understanding tasks specifically. |
| **Phi-3.5-Vision (4B)** | Microsoft's small but capable model. Very efficient to fine-tune on limited compute. |

### Tier 2 — If you have access to a university GPU cluster
| Model | Notes |
|---|---|
| **LLaVA-1.6 34B** | Much more capable but needs multi-GPU setup |
| **Qwen2-VL 72B** | SOTA open VLM but very resource heavy |

### Fine-tuning tooling to know about
- **LLaMA-Factory** — supports most of the above models for SFT, has VLM fine-tuning built in, relatively easy to configure
- **HuggingFace TRL** — more flexible but lower-level
- **Unsloth** — dramatically reduces VRAM requirements, supports some VLMs; great for a resource-constrained setup
- **LoRA / QLoRA** — you almost certainly want to use parameter-efficient fine-tuning (LoRA) rather than full fine-tuning. QLoRA (quantized LoRA) can get a 7B VLM fine-tunable on a single 24GB GPU

---

## Recommended Starting Path

Given everything above, here's a concrete sequence I'd suggest:

1. **Establish a zero-shot baseline** with GPT-4o or Gemini using a structured prompt (before+after image + task + code). Measure agreement with UIX designer labels. This is your ceiling and sanity check.
2. **Choose Qwen2-VL 7B or InternVL2 8B** as your fine-tuning target — both punch above their weight on UI-related visual tasks.
3. **Format your UIX designer data** as visual instruction tuning pairs (image pair + task → pass/fail + reasoning).
4. **Fine-tune with QLoRA via LLaMA-Factory** — reduces the hardware requirements significantly.
5. **Compare fine-tuned model vs. zero-shot baseline** on a held-out test set. Agreement with UIX designers is your primary metric.

One final thought: using **both the image and the code** as input is a meaningful differentiator from naive VLM approaches and could be a genuine contribution of your work — it's a more grounded evaluation signal than image-only, and not all prior work does this.