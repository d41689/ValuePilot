# ValuePilot Investment Research Vision

> **Status:** Non-Normative Vision
>
> **Purpose:** Describe ValuePilot's investment-research philosophy, long-term
> product principles, and conceptual capabilities.
>
> **Origin:** Curated from the frozen 7,056-line research compendium preserved in
> commit `626f797`.
>
> **Last updated:** 2026-08-20

This document does **not** define:

- database schemas or storage fields;
- API contracts;
- canonical metric keys, units, or period semantics;
- state enums or lifecycle transitions;
- implementation sequencing;
- release or acceptance criteria;
- source acquisition rights;
- broker execution or trading authority.

In a conflict, the canonical mapping spec, authoritative PRD, locked data
contracts, [Research Decision Support architecture](architecture/research-decision-support.md),
and approved product roadmap take precedence. Worked examples are illustrative
only. The consolidated EXLS example lives in
[the EXLS investment-research case study](examples/exls-investment-research-case-study.md).

---

## 1. Vision

ValuePilot aspires to be a persistent investment-intelligence and
decision-support system for a serious, self-directed long-term investor.

Its purpose is not to replace judgment. It is to help the investor:

- remember facts, assumptions, and decisions over long periods;
- understand businesses consistently;
- preserve source evidence and uncertainty;
- express testable investment hypotheses;
- notice economically meaningful change;
- search actively for contradictory evidence;
- update valuation assumptions when the underlying evidence changes;
- recognize high-quality businesses at attractive prices;
- compare opportunities and allocate research attention;
- review decisions without hindsight bias;
- avoid repeating preventable mistakes.

The objective is better decisions, not more decisions, more alerts, more model
output, or more trades.

```text
Facts
  -> Evidence
  -> Business understanding
  -> Hypotheses
  -> Investment thesis
  -> New evidence
  -> Thesis and valuation delta
  -> Opportunity review
  -> Human decision
  -> Outcome and postmortem
  -> Better future judgment
```

## 2. Place in ValuePilot

Investment research is downstream from ValuePilot's differentiated discovery
and data capabilities; it does not replace them.

Conceptually, ideas may arrive from several parallel surfaces:

```text
Value Line quality/growth evidence -----+
13F / Oracle's Lens --------------------+
Watchlist ------------------------------+--> private research case
Screener or stock summary --------------+
Manager holding/change -----------------+
Manual investor idea -------------------+
```

Value Line can contribute structured fundamental evidence and separately
labeled valuation references. 13F and Oracle's Lens can contribute delayed,
caveated discovery and corroboration. Watchlist can represent current user
interest. None of these sources is an investment decision.

The durable judgment belongs to the user. Shared company identity and permitted
facts remain distinct from private research, valuation, notes, and decisions.
The normative ownership and integration boundary lives in the architecture,
not in this Vision.

## 3. Investment constitution

ValuePilot's investment experience is guided by these principles:

1. Facts before opinions.
2. Primary evidence before secondary commentary.
3. Source reliability is not the same as source relevance.
4. Fact, interpretation, hypothesis, valuation, and decision are different.
5. Persistent research memory is preferable to a fresh narrative every quarter.
6. Persistent memory must be challenged so that it does not become anchoring.
7. A moat is a testable economic hypothesis, not a label.
8. Growth quality matters more than growth rate alone.
9. Incremental returns matter more than historical averages alone.
10. Owner economics matter more than adjusted storytelling.
11. Business quality and market price are evaluated separately.
12. Intrinsic value is uncertain and is better expressed as a range.
13. Market expectations matter as much as a standalone forecast.
14. Contradictory evidence is a first-class research input.
15. Every important thesis needs falsification or kill criteria.
16. Missing information and known unknowns remain visible.
17. Price changes do not automatically equal business changes.
18. Option premium is downstream from fundamental underwriting.
19. Do nothing is a valid capital-allocation decision.
20. Historical decisions are judged using information available at the time.
21. AI proposes and challenges; the investor accepts and publishes.
22. The final investment judgment remains human.

## 4. Persistent investment memory

ValuePilot's central research question is:

> What changed relative to what the investor previously believed?

A quarterly AI report that starts from a blank page loses assumptions,
unresolved questions, disconfirming evidence, and the reasons a valuation moved.
A useful investment memory instead preserves the evolving chain:

```text
Accepted research view
        +
New source evidence
        -> proposed delta
        -> skeptical challenge
        -> human review
        -> accepted revision or no change
```

Persistent memory reduces repeated work and narrative drift, but it creates its
own risk: thesis inertia. Important holdings and high-priority research deserve
periodic clean-sheet review in which the investor temporarily ignores the old
conclusion and asks whether the business would still merit study today.

Research memory is user-owned. ValuePilot's strategic asset is the capability
to help users accumulate an auditable intellectual history, not ownership of
their private thesis content.

Over time, a user may ask:

- Why did this company first enter research?
- Which evidence supported the original moat hypothesis?
- What contradicted it?
- Which assumptions changed and why?
- What was believed on a specific historical date?
- Why did the valuation range move?
- Which uncertainty remained unresolved?
- What decision was made with the information then available?
- What was learned afterward?

## 5. Facts, claims, evidence, and interpretation

Investment reasoning becomes more reliable when it distinguishes different
levels of knowledge.

```text
Reported or derived fact
    -> used as evidence for a particular question
    -> interpreted in context
    -> supports or contradicts a hypothesis
    -> may influence valuation and a human decision
```

A management statement is a claim, not a verified operating outcome. An audited
number can be reliable evidence of a historical result but weak evidence of a
future moat. A customer observation may be anecdotal for market share yet useful
for discovering a research question.

Evidence is considered along several independent dimensions:

- source identity and authority;
- whether it is reported, derived, estimated, inferred, or claimed;
- verification status;
- relevance to the hypothesis;
- directness and independence;
- reporting and publication date;
- persistence or recency;
- supporting, contradicting, mixed, or unresolved direction;
- materiality to the investment decision.

Repeated reporting does not create repeated independent evidence. A filing,
earnings release, news article, analyst note, and social post may describe one
underlying event. Corrections and retractions also matter; later authority does
not erase what the investor knew earlier.

Missing and inaccessible evidence remains explicit. A model-generated estimate
may be useful when clearly labeled with assumptions, but it does not become a
reported fact through confident prose.

## 6. Business understanding and circle of competence

Before scoring or valuing a company, research tries to understand its economic
engine:

1. What does the company sell?
2. Who pays and why?
3. How does the company get paid?
4. Which revenue streams have attractive economics?
5. What determines unit economics and profitability?
6. What capital is required to grow?
7. What determines long-term growth?
8. What could permanently damage the business?
9. Which variables are measurable?
10. Which variables remain outside the investor's competence?

“We do not understand this business well enough” is a valid conclusion. High
reported growth or a low multiple does not override low understanding.

For businesses inside the circle of competence, research identifies a small set
of key decision variables: the assumptions that most affect thesis confidence,
downside, or valuation. Research attention goes toward high-impact,
high-uncertainty questions rather than low-impact detail.

## 7. Testable hypotheses

Moat, growth, capital allocation, and risk are most useful when represented as
questions that evidence can challenge.

A conceptual hypothesis contains:

- a clear claim;
- an economic mechanism;
- a relevant time horizon;
- supporting and contradicting evidence;
- key observable indicators;
- important dependencies;
- material unknowns;
- falsification or review conditions;
- the investor's qualitative confidence;
- the date and context of the accepted view.

Examples of moat mechanisms include switching costs, network effects, cost
advantage, brand, distribution, scale, regulation, data, or operational
complexity. These are possible sources, not proof. Proof is sought in customer
behavior, pricing power, retention, market-share economics, competitor response,
and sustained returns on incremental capital.

Growth hypotheses distinguish organic growth, pricing, volume, acquisition,
foreign exchange, and per-share effects. The central question is not merely how
fast a company is growing, but why it is growing, what capital it consumes, and
how long the driver can persist.

Risk hypotheses emphasize permanent impairment, survival, balance-sheet
resilience, accounting credibility, management integrity, competition,
regulation, concentration, technology, and capital allocation.

Qualitative claims such as “the moat is durable” generally use qualitative
confidence and explicit evidence. Probabilities are reserved for propositions
with a defined resolution rule and date, such as whether a specified operating
metric will exceed a threshold in a named fiscal year.

## 8. Anti-confirmation-bias design

For every serious candidate, research develops the strongest plausible bull and
bear cases. The goal is not artificial balance; it is to locate the real
disagreement between intelligent investors and identify what evidence would
distinguish the explanations.

A skeptical review asks:

- What is the strongest alternative explanation?
- Are temporary conditions being extrapolated?
- Is correlation being mistaken for causation?
- Are management incentives shaping the narrative?
- Could accounting presentation overstate owner economics?
- What would a knowledgeable competitor, customer, or short seller argue?
- Which missing evidence would most change the conclusion?
- Has familiarity with the company become emotional attachment?

Unknown unknowns cannot be enumerated, but blind spots can be acknowledged
through conservative assumptions, scenario breadth, research limits, and a
willingness to pass.

Falsification conditions work best when precommitted. A threshold with an
unbounded “unless there is a good explanation” exception invites hindsight.
Human overrides may be reasonable, but the reason belongs in the decision
history.

## 9. Buffett/Munger business-quality lens

The quality lens asks economic questions rather than relying on one composite
score:

- Why can customers not easily replace the business?
- Does it possess durable pricing power?
- How predictable are its economics?
- How capital-intensive is growth?
- What does each additional dollar of retained capital produce?
- How long can excess returns persist?
- Can attractive returns be reinvested at meaningful scale?
- Does management allocate capital rationally and candidly?
- Is the moat strengthening, stable, weakening, or uncertain?
- Is the business likely to be stronger in ten years?

Scores may help organize research, but they remain indexes of evidence, not
investment truth. A precise-looking `8.1/10` can conceal uncertainty or a fatal
single risk. Explanations, evidence, trend, and unresolved questions matter more
than decimal precision.

### Owner economics

Owner Earnings is a way of thinking about distributable economic earning power,
not a universal formula. Reported net income and free cash flow may require
adjustment for maintenance investment, working capital, stock-based
compensation, leases, capitalized development, acquisitions, cyclicality, and
other business-model-specific factors.

Banks, insurers, software companies, semiconductor manufacturers, industrials,
REITs, and commodity producers do not share one Owner Earnings or invested-
capital policy. Any deterministic implementation belongs to versioned,
industry-appropriate policy outside this Vision.

### Incremental returns and reinvestment

High historical ROIC is most valuable when the business also has a long runway
to reinvest at attractive incremental returns. A business with exceptional
returns but no reinvestment opportunity may compound less value than a business
with moderately lower returns and a long, defensible runway.

Incremental return analysis is inherently noisy. Acquisitions, goodwill,
leases, excess cash, negative invested capital, cyclicality, and financial
businesses require explicit treatment. The purpose is disciplined inquiry, not
the appearance of accounting certainty.

## 10. Management and capital allocation

Management assessment covers more than guidance accuracy. It considers:

- integrity and candor;
- incentive design and related-party behavior;
- capital-allocation history;
- accounting choices;
- succession and key-person dependence;
- treatment of shareholders on a per-share basis;
- behavior during industry or market stress;
- promises compared with later outcomes.

Capital allocation is reviewed across organic reinvestment, acquisitions,
buybacks, dividends, debt, stock-based compensation, and asset sales.

Stock-based compensation is an economic cost. Gross buyback announcements are
considered alongside dilution and the net change in each owner's share of the
business. Buyback quality is judged using information and valuation assumptions
available at the time, not a later hindsight valuation.

Acquisition review acknowledges disclosure limits. Expected synergies and
cohort economics may be management claims, estimates, non-separable, or
unavailable after integration. Unobservable precision is not manufactured.

## 11. Growth and competitive context

Company growth is examined relative to industry growth, pricing, market-share
change, product expansion, geography, acquisition, currency, and capital
requirements. Faster company growth than a broad industry estimate may suggest
share gain, but product, segment, customer, and geographic mix can produce the
same appearance.

A company is compared with economically relevant competitors rather than in
isolation. Comparison may include organic growth, margins, capital intensity,
incremental returns, customer concentration, retention, pricing, balance-sheet
resilience, dilution, and valuation.

Industry and business-model context matters. Useful analytical templates may
cover areas such as:

- SaaS: ARR, retention, churn, RPO, gross margin, CAC and LTV;
- semiconductors: units, ASP, inventory, utilization, node mix and CapEx;
- insurance: underwriting profitability, reserve development and investment
  economics;
- banks: credit quality, funding, capital, liquidity and through-cycle returns;
- IT services/BPO: organic growth, headcount, utilization, revenue per employee,
  bookings and concentration;
- industrial/cyclical businesses: capacity, replacement demand, inventory,
  pricing, cycle position and balance-sheet survival.

Templates create consistent questions without forcing every company into a
generic formula.

## 12. Change detection and causal reasoning

When new data arrives, the preferred reasoning order is:

```text
Detect the numerical or factual change
  -> measure magnitude
  -> compare with history and prior expectation
  -> identify alternative causes
  -> map relevant evidence to open hypotheses
  -> search for contradiction
  -> propose a thesis or valuation delta
  -> request human review when material
```

Change detection comes before explanation so that a narrative is not chosen
first and fitted to the numbers later.

Management guidance is evidence, not fact. A useful history compares original
guidance, revisions, assumptions, and actual outcomes. Language and Q&A changes
may reveal demand, pricing, customer, competition, and execution concerns, but
semantic change requires context and should not be reduced to generic sentiment.

Leading indicators depend on the business model. Bookings, backlog, retention,
traffic, utilization, pipeline, inventory, or capacity can be useful only when
their definitions and relationship to future economics are understood.

Base rates help resist unrealistic extrapolation. They inform the outside view
but do not automatically override strong company-specific evidence.

## 13. Valuation philosophy

Business quality and stock valuation are displayed separately. They share some
economic assumptions, but a quality judgment is not allowed to become attractive
merely because the stock price fell.

Valuation is approached as a range of possible outcomes rather than a precise
target price. Bear, base, and bull cases reflect different economic hypotheses,
not arbitrary percentage changes. Assumptions may include normalized owner
earnings, growth, margins, capital requirements, competitive-advantage period,
dilution, balance sheet, discount or opportunity cost, and terminal economics.

Reverse DCF provides a useful expectations check:

> What growth, margins, reinvestment, and competitive duration must be true to
> justify the current market price?

The answer can be compared with the research view and relevant base rates.

Margin of safety is not one universal threshold. A useful review considers both
base-case and bear-case relationships, together with valuation date, price date,
currency, business predictability, leverage, and uncertainty. A positive base
MOS with negative bear-case MOS communicates more than one headline percentage.

Valuation changes are explained through assumption deltas rather than arbitrary
target-price changes. A system reference or analyst target remains visibly
different from the user's accepted and published intrinsic value, as required by
the architecture and PRD.

## 14. Expected return and opportunity cost

Expected return is a scenario-dependent estimate, not a promise. Its conceptual
sources include growth in per-share owner earnings, cash distributions, dilution
or net repurchase effects, and change in valuation. Components are defined so
that buybacks are not counted twice through both per-share growth and a separate
yield.

Two opportunities with the same central expected return can have very different
downside, dispersion, liquidity, leverage, and confidence. Subjective confidence
does not mechanically multiply expected return; it informs scenario breadth,
required margin of safety, and the willingness to pass.

The relevant capital-allocation question is not merely whether one company is
attractive, but whether it is more attractive than the alternatives available
for the same capital. Cash and inaction are valid alternatives.

## 15. Downside, stress, and kill criteria

The primary risk is permanent capital impairment rather than ordinary price
volatility. Research distinguishes:

- permanent business deterioration;
- balance-sheet or refinancing failure;
- accounting or management-integrity loss;
- temporary cyclical drawdown;
- valuation compression;
- concentration and portfolio interaction;
- recovery path and time.

Stress scenarios vary by business. Revenue decline, margin pressure, customer
loss, credit deterioration, higher funding cost, recession, capacity imbalance,
or technological displacement may be more relevant in different industries.

Watch conditions indicate concerns requiring observation. Kill criteria indicate
events that can break the thesis rather than merely subtract a few points from a
score. Triggering either creates a need for human review; it does not automate a
trade.

## 16. Research attention and patience

Not every company deserves the same depth or frequency of research. Attention
can reflect:

- an owned or watched decision awaiting review;
- magnitude of new contradictory evidence;
- importance of an unresolved question;
- potential impact on downside or valuation;
- availability of evidence that could resolve the question;
- current valuation relevance;
- portfolio exposure and concentration.

Low likelihood of obtaining new evidence does not make a critical unknown
unimportant. It may instead make the business ununderwritable.

Price can change opportunity without changing the accepted business thesis, but
a large unexplained move first warrants a check for missing information. “The
system has not detected a change” is not proof that nothing changed.

Patience is an explicit feature. An excellent business with no margin of safety
may remain in `WAIT` conceptually without requiring a transaction.

## 17. Options as underwriting

Put analysis is an optional branch downstream from fundamental research, not a
mandatory stage and not a trading rail.

The central underwriting question is:

> Would the investor genuinely want to own the business at the effective
> assignment economics if assignment occurred?

Premium is a final filter, not the reason to like the business. A high premium
does not repair a weak thesis or unsafe balance sheet.

Conceptual analysis may consider strike, premium, expiry, DTE, liquidity,
bid/ask spread, implied volatility, collateral basis, events, assignment
exposure, portfolio concentration, and the accepted research revision. The
simple expression `strike - premium` is a gross per-share comparison before
fees, taxes, contract adjustments, and other economic effects.

Option-chain acquisition requires separately authorized source policy. Analysis
ends with a human review or decision record. Broker execution, routing, margin
management, assignment operations, and tax reconciliation are outside this
Vision and expressly excluded by the architecture.

## 18. Portfolio lens and position sizing

Company analysis is necessary but not sufficient. Several tickers may share the
same economic exposure through customer budgets, funding, geography, commodity
inputs, regulation, or technology.

Portfolio analysis distinguishes overlapping dimensions rather than adding them
into one taxonomy:

- sector and industry;
- business driver;
- factor and cycle exposure;
- geography and currency;
- customer or supplier concentration;
- liquidity and leverage;
- option assignment exposure.

Position sizing remains human judgment. Quality, margin of safety, uncertainty,
permanent-loss scenarios, liquidity, correlation, existing exposure, and risk
budget can inform that judgment. A subjective high score is not permission for
automatic concentration.

## 19. Human research rhythms

Conceptually, different cadences serve different purposes:

- **Daily:** detect filings, source corrections, material evidence changes,
  coverage failures, unexplained price moves, and valuation-zone crossings.
- **Weekly:** review thesis conflicts, falsification alerts, overdue obligations,
  major valuation changes, unresolved questions, and a small number of new
  candidates.
- **Quarterly:** compare reported outcomes with prior internal expectations,
  guidance, operating drivers, capital allocation, and competitive position.
- **Annually:** conduct a clean-sheet thesis review and revisit the strongest bull
  and bear cases without allowing current price or ownership to dictate quality.

The ideal output is not a large summary. It is a short, explainable queue of
decision-relevant work, including missing, stale, inaccessible, and failed data.
No-news is not automatically a healthy state.

## 20. AI as research assistant

AI is useful for observation, extraction, comparison, hypothesis proposals,
contradiction search, alternative explanations, and concise synthesis. It is
especially valuable when it helps the investor remember what changed and why a
question remains unresolved.

AI is not an autonomous analyst of record. It does not silently maintain the
user's accepted thesis or published valuation. The authority sequence is:

```text
AI observes, extracts, compares, proposes, and challenges
        -> user accepts, rejects, or edits
        -> user explicitly saves or publishes under the architecture contract
```

Deterministic financial and option calculations belong in deterministic,
versioned code. Model output preserves citations and material assumptions when
the governing product contract permits persistence. A “skeptic agent” is not
automatically independent merely because it has a different name; useful
red-team review needs deliberately separated instructions and evidence handling.

## 21. Decision journal and learning

A meaningful decision record captures what the investor believed, expected,
feared, valued, and decided using information available at the time. It may
record watch, pass, own, continue to wait, reduce, exit review, or an option-
underwriting decision without implying broker execution.

Postmortem distinguishes process from outcome:

```text
Good process + good outcome
Good process + bad outcome
Bad process + good outcome
Bad process + bad outcome
```

Bad process with a good outcome is especially dangerous because profit can
reinforce poor reasoning.

Review asks which assumptions resolved, which risks materialized, whether the
margin of safety was adequate, whether contrary evidence was ignored, and what
process change could reduce a preventable error. Missed opportunities are not
declared mistakes merely because the stock later rose.

Calibration is reserved for claims that can be resolved honestly. Historical
review uses frozen contemporaneous evidence, assumptions, identity, price, and
policy versions so that later knowledge does not leak backward.

## 22. Human-facing research experience

The daily decision view favors compact clarity:

- business and understanding summary;
- accepted thesis and current review state;
- dated valuation range and eligible price comparison;
- most important new evidence;
- strongest contradiction;
- primary unresolved question;
- falsification or kill-condition status;
- provenance and missing-data state;
- explicit human next action.

Deeper inspection can expose financial history, evidence, competing hypotheses,
industry context, valuation assumptions, management history, decision revisions,
and optional underwriting analysis.

The interface hides incidental complexity, not uncertainty, source conflict, or
data failure.

## 23. What ValuePilot should not become

ValuePilot is not intended to become:

- a news aggregator optimized for volume;
- an opaque stock-ranking model;
- a target-price generator that hides assumptions;
- a source-free LLM opinion machine;
- a confirmation-bias amplifier;
- an autonomous trading bot;
- a broker, tax, or portfolio-reconciliation system;
- a platform that treats private user research as shared intellectual property.

## 24. Long-term aspiration

Over time, ValuePilot can help an investor develop reusable understanding across
companies and industries: better base rates, better causal questions, clearer
evidence standards, and a more honest record of mistakes.

The product succeeds when the investment process no longer resets each time a
company is reopened:

```text
Research compounds.
Evidence accumulates without losing provenance.
Understanding becomes more precise.
Contradiction remains visible.
Judgment improves.
Mistakes become reusable lessons.
```

The final principle is simple:

> Automate evidence collection, memory, comparison, and disciplined challenge;
> do not automate the investor's opinion or allocation of capital.
