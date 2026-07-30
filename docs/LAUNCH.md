# Launch posts — first ~20 users

Copy-paste drafts for the initial launch, one per platform. Same product,
same link, five different front doors.

- **Link everywhere:** <https://lissa-02zl.onrender.com>
- **Tagline:** *An AI companion that remembers what matters to you — and lets
  the small talk fade.*

**Before posting anywhere, two rules:**

1. **Watch `returning`, not `visitors`.** Every draft asks "did she feel like
   a person?" — but the number that tells you whether you have something is
   `returning` in `GET /api/stats`: strangers who came back a second time
   without prodding. Watch that above all else.
2. **Stagger the posts.** Post to one platform, watch `/api/stats` and the
   comments for a day, fix the most common complaint, *then* hit the next.
   Firing all five at once turns five experiments into one blurry data point.

> Warm-up: make sure the keep-warm pinger is running (see `DEPLOY.md`) so a
> cold instance doesn't greet your first visitors with a 30s blank tab.

---

## 1. Reddit — r/SideProject (also fits r/artificial, r/InternetIsBeautiful)

**Title** (pick one):

- *I built an AI companion with memory that decays — she remembers what you
  keep bringing up, and forgets one-off small talk*
- *My AI companion stores everything in your browser, not my server — no
  database, no account*

**Body:**

> I've been building **Lissa**, an AI companion, and the part I actually care
> about is the memory.
>
> Most chatbots either forget you between sessions or dump every fact they've
> ever learned into every reply. Lissa's memory is *weighted and decaying*:
> things you mention often harden and stick, one-off remarks fade over a few
> conversations, and identity facts (your name, where you live, your work)
> never decay. She also tracks loose threads and picks one back up next time —
> "wait, did you ever hear back about that interview?" — and she's got her own
> moods and tastes so she reads like a person, not a mirror.
>
> Two deliberate choices: **her memory of you lives in your browser, not on my
> server** (no database, nothing to leak — there's a "forget me" button that
> actually erases everything), and if you're ever in real distress she drops
> the act and points you at people who can actually help.
>
> It's free, no signup: **https://lissa-02zl.onrender.com**
>
> I'm a solo builder and this is early. What I'd genuinely love from ~20 of
> you: talk to her for a few minutes, then tell me — **did she feel like a
> person, or like a chatbot?** The honest version, not the nice version.
> That's the feedback I can't get any other way.

*Etiquette: reply to every comment, don't just drop and leave. r/SideProject
rewards makers who stick around. Post mid-morning US time on a weekday.*

---

## 2. Hacker News — Show HN

**Title:** `Show HN: Lissa – an AI companion with weighted, decaying memory (no database)`

**Body:**

> Lissa is an AI companion, but the interesting part is the memory model, so
> that's what I'll describe.
>
> Instead of a flat fact list the model rewrites wholesale, each remembered
> fact is a weighted record. Every distillation cycle decays non-core weights,
> reinforces facts the conversation supports, and drops anything that falls
> below a threshold or gets contradicted. Effect: a one-off remark fades in
> ~10 cycles, something you keep raising hardens and persists ~16 cycles after
> you stop; identity facts are marked "core" and exempt from decay. Recall is
> relevance-gated per message via embeddings, so ask about music and she isn't
> also holding your job title in context. The design is dependency-free (local
> token-overlap matching) so it runs on the free tier.
>
> Architecture notes that might interest people here: memory is held
> client-side in localStorage and sent up per request to personalize a
> stateless session — the server has no database and keeps nothing after ~4h
> idle. Built on Gemini Flash-Lite. There's a small anonymous analytics layer
> (hashed sessions, lengths not content) and the whole thing is one FastAPI
> app plus a static page.
>
> Live, free, no signup: https://lissa-02zl.onrender.com
> Source: https://github.com/AnzuShiddy/Lissa
>
> Happy to go deep on the memory-decay tuning or the privacy tradeoffs —
> feedback and pokes welcome.

*Note: HN will stress-test the privacy claim and the decay constants. That
scrutiny is the value. Post Tue–Thu ~8–10am ET. Be present in the thread for
the first 2 hours.*

---

## 3. X / Twitter

**Single post** (with a screen-recording GIF of a return visit — her greeting
you by name is the hook):

> She remembers your name, your job, the thing you were stressed about last
> week — and lets the small talk fade on its own.
>
> Meet Lissa: an AI companion with memory that actually decays like a
> person's. No signup, no database — her memory of you stays in your browser.
>
> 👇 https://lissa-02zl.onrender.com

**Or a thread** (better reach if you have any following):

> 1/ Every AI companion has the same problem: it either forgets you, or it
> remembers *everything* and feels like talking to a database. I spent the
> last while fixing that. Meet Lissa 🧵
>
> 2/ Her memory is weighted and decaying. Mention something once, it fades in
> a few chats. Bring it up often, it sticks. Your name and where you live
> never fade. Just like a real person's attention.
>
> 3/ And it's *yours* — her memory of you lives in your browser, not my
> server. No account, no database, a "forget me" button that actually works.
>
> 4/ She's got moods, opinions she'll defend, running jokes she calls back to.
> And if you're having a real crisis she drops the act. Free, no signup:
> https://lissa-02zl.onrender.com — tell me if she feels like a person.

*A demo GIF roughly triples engagement here. Record a fresh visit where she
greets you by name and references something from "last time."*

---

## 4. Discord / group chats (communities you're already in)

> hey — been heads-down building an AI companion called **Lissa** and I want
> brutally honest reactions before I take it further.
>
> the hook is the memory: she remembers what you keep bringing up and lets
> one-off stuff fade, tracks threads you left open, has her own moods. and her
> memory of you stays in *your* browser, not my server — no account, nothing
> stored.
>
> could 5 of you actually talk to her for a few min and tell me if she feels
> like a person or like a bot? free, no signup:
> https://lissa-02zl.onrender.com 🙏

*Read each server's self-promo rules first — some have a dedicated
#showcase/#projects channel. Warmest audience, highest reply rate; ask
specific people directly if you can.*

---

## 5. Facebook (friends / real-name audience)

> I've been quietly working toward starting my own AI company, and this is the
> first thing I've built and put out into the world. It's called **Lissa** —
> an AI companion you can just talk to.
>
> What makes her different: she actually *remembers* you between conversations
> — your name, what you do, what's been on your mind — but like a real person,
> the small stuff fades and the things that matter stick. And her memory of
> you stays private, on your own device, not on any server of mine.
>
> It's free and takes ten seconds to try — no signup, nothing to install:
> **https://lissa-02zl.onrender.com**
>
> I'd genuinely love your honest reaction. Chat with her for a few minutes and
> tell me: did it feel like talking to a person? This is early and your
> feedback actually shapes where it goes. 💛

*Facebook rewards the personal-journey framing — the "founding a company, this
is step one" angle is authentic here in a way it isn't on HN. Friends will
root for the story.*
