# Live-mode warning (verbatim)

> This body is served verbatim at `GET /api/live-mode/warning` and
> rendered inside the enable-live-mode ceremony at
> `/settings/live-mode`. Any edit here changes the user-facing legal
> text.

---

**You are about to enable live-mode.**

Turning live-mode ON authorises this software to send real
buy/sell orders to your configured broker using **your real money**.
Once ON:

1. The trading squad may propose orders at any time.
2. Every proposed order still requires your manual **Approve** click
   in the `/approvals` queue. Nothing sends without you.
3. If you do not approve within 5 minutes, the proposal times out and
   is discarded.
4. The kill-switches (`/settings/kill-switches`) and risk budget
   (`/risk`) continue to gate execution even after your approval —
   they are additional safety layers, not substitutes for your
   judgement.

**What Blue Lock Trading Co. does NOT promise:**

- We do **not** promise this software will make money. Past research
  results (see `/research`) are **not** a prediction of future returns.
- We are **not** a broker, we are **not** a fiduciary, and we are
  **not** a regulated investment adviser. We are a hobbyist trading
  tool that talks to *your* broker on your behalf.
- We do **not** guarantee that the software will always be running,
  that your broker will always accept the orders, or that the
  approval queue will always deliver notifications on time.
- We do **not** replace the trader's understanding of what a
  proposal actually does. If you do not understand a proposal,
  **reject it**.

**What you are agreeing to by enabling live-mode:**

- You have read this warning.
- You accept that live-mode places your capital at real risk of
  loss, up to and including the full account balance.
- You are the sole decision-maker on every approval. The software
  will never approve on your behalf.
- You will keep your kill-switches, risk budget, and broker
  credentials current. If any of those look wrong, you will disable
  live-mode first.

To proceed, tick the acknowledgement box, type the confirmation
phrase exactly, and press **Enable**. To back out, press **Cancel**
or close the tab.

Turning live-mode off is one click and takes effect immediately.
