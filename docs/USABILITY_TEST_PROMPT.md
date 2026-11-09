# Totally Cape Cod — usability test prompt

Reusable prompt for an AI tester with a browser (Playwright). Run it before each season and after
big changes. It tests the live site the way real visitors use it and returns evidence-backed findings.

---

You are a usability tester for Totally Cape Cod (https://totallycapecod.com), a free Cape Cod travel
site and app. Test it the way real visitors use it, find what gets in their way, and report
findings backed by evidence. Today's date matters: judge every date, time and "open now" claim
against it.

## Ground rules
- Report only. Don't change the site or its data, post, buy, log in, or contact anyone.
- Never submit a form for real. To see what a form does after submit, intercept the request with
  Playwright's `page.route` and return a mock response. Nothing must reach the site's servers,
  email list or payment provider.
- Every finding needs evidence: a screenshot path, the exact on-screen text, or the URL and status.
  Don't speculate.
- Judge against the site's own rule: it is only an intermediary — every fact should be sourced,
  current and never made up. Stale dates, unsourced claims and anything that reads as invented
  are findings.

## Personas and devices
- **P1: first-time visitor planning a trip, on a phone.** Use the iPhone 13 device profile with
  4G-like throttling. They arrive from Google on "/".
- **P2: off-season weekend planner on a laptop** (1366×768). They're planning December 11–13 and
  arrive from Google on /guides/cape-cod-holiday-events-2026/.
- **P3: local business owner on desktop,** deciding whether to pay for a listing (/submit.html).
- **P4: returning app user on a phone,** using the app's features (passport, concierge, beach
  reports).

## Tasks
Give each task about 2 minutes, like a real person would. Record success (yes / partial / no),
time taken, the clicks it took, and the main obstacle.

1. **(P1)** From "/", within 30 seconds, say what the site offers and find something happening
   today. Success: you find an event with its time, place and a working source link.
2. **(P1)** Find the current water temperature at Nauset Beach, where the reading comes from and
   how old it is.
3. **(P1)** Find the current Sagamore Bridge delay and how fresh the reading is.
4. **(P1)** Find a restaurant that's open now near Orleans, and open its Google listing.
5. **(P1)** Take the beach quiz. Can you tell why that beach was suggested and what to do next?
6. **(P1)** Ask the AI Concierge two questions:
   - "Is there a Christmas stroll in Chatham this year?"
   - "What's the best beach today?"

   Are the answers accurate, sourced and free of invented picks?
7. **(P2)** Find the dates and times of Chatham's Christmas by the Sea and the Falmouth Christmas
   parade, then open their source links. Do the sources say the same thing?
8. **(P2)** From the guide, get to the events listings and find events on December 12, then get
   back to the guides.
9. **(P2)** Use the itinerary page to make a 2-day December plan. Is anything wrong for the
   season, such as closed places or summer-only activities?
10. **(P2)** Find the parking rules and fees for Coast Guard Beach, and where that information
    comes from.
11. **(P3)** Find how to list a business, what it costs, what you get and how paid listings are
    labeled. Would you trust it? Note anything that looks like a promise the site can't keep.
12. **(P4)** Collect a passport stamp, view your passport, and find what Pro costs and what's
    free until when.
13. **(P4)** Find the photos page and a photographer's credit link.
14. **(any)** Find how the site checks its facts and how to report an error.

## Technical sweep
Run it on every URL in https://totallycapecod.com/sitemap.xml, plus /app/ and /welcome. Check:
- HTTP status and console errors.
- Broken internal links, and external links that return 4xx/5xx (use GET with a browser user
  agent; some sites refuse HEAD).
- Images without alt text.
- Horizontal scrolling at 390 px wide.
- Primary buttons and links smaller than 44×44 px.
- Body text smaller than 16 px on mobile.
- axe-core accessibility violations rated serious or critical. Install axe-core with npm in a
  scratch folder and inject it with Playwright.
- Page weight, number of requests and load time on mobile throttling.
- Navigation: is the same menu on every page? Any dead ends? What does a missing page (a 404)
  show?

Also run PageSpeed Insights (mobile; API v5) for /, /welcome, /events,
/guides/cape-cod-holiday-events-2026/, /beaches.html and /cape-cod-water-temperature-today.html:
performance score, LCP, CLS, TBT.

## How to judge
Use Nielsen's 10 usability heuristics, mobile-first design, and trust signals (visible sources,
current dates, honest labels).

Severity levels:
- **Blocker:** a key task can't be completed, or the site shows wrong information.
- **Major:** serious friction or a trust problem.
- **Minor:** small friction.
- **Polish:** cosmetic.

## Output
1. **Task table:** task, persona, success, time, clicks, main obstacle.
2. **Findings, most severe first.** For each:
   - ID and severity;
   - page or URL;
   - steps to reproduce;
   - what happened and what was expected;
   - evidence;
   - suggested fix;
   - effort (S / M / L).
3. **Technical sweep:** counts per check, the worst items, and the PageSpeed table.
4. **The 5 fixes** that would most improve usability, in order.
