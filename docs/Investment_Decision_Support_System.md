# ValuePilot Investment Decision Support System

> **Status:** Architecture Baseline  
> **Purpose:** Define the long-term architecture and investment philosophy of ValuePilot  
> **Core Principle:** AI maintains facts, theses, evidence, changes, and valuation state. The investor makes the final investment decision.

---

# 1. Vision

ValuePilot should evolve from a stock screener / option trading tool into an:

# Investment Decision Support System

The purpose of ValuePilot is **not** to replace the investor.

Its purpose is to help the investor:

- remember better;
- collect facts systematically;
- understand businesses consistently;
- maintain investment theses over long periods;
- identify meaningful changes earlier;
- actively search for evidence that contradicts existing beliefs;
- update valuation assumptions when facts change;
- discover high-quality companies at attractive prices;
- identify attractive Put underwriting opportunities;
- make better final investment decisions.

The system should therefore optimize for:

> **Decision Quality**

rather than:

> **Autonomous Decision Making**

The fundamental workflow is:

```text
Facts
  ↓
Business Understanding
  ↓
Investment Thesis
  ↓
New Evidence
  ↓
Thesis Delta
  ↓
Valuation Delta
  ↓
Opportunity Detection
  ↓
Human Review
  ↓
Human Decision
```

---

# 2. The Most Important Architectural Principle

ValuePilot must **not** behave like an AI analyst that rereads a company from scratch every quarter and generates a completely new opinion.

Instead, every company should have a persistent:

# Company Investment Memory

or:

# Company Thesis State

When new information arrives, the central question is:

> **What changed?**

The correct model is:

```text
Previous Thesis
      +
New Evidence
      ↓
Thesis Delta
```

NOT:

```text
New Filing
    ↓
Fresh AI Opinion
```

This distinction is fundamental.

Without persistent thesis state, the system will suffer from:

- narrative drift;
- inconsistent scoring;
- forgotten assumptions;
- repeated research;
- confirmation bias;
- inability to explain why conclusions changed.

With persistent thesis state, ValuePilot can build a genuine institutional investment memory.

---

# 3. Target Architecture

The long-term architecture should look approximately like this:

```text
                 ┌──────────────────────┐
                 │   Company Universe   │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Fact / Data Layer  │
                 │ SEC / Earnings / etc │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Business Model     │
                 │     Understanding    │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │    Thesis Engine     │
                 │ Moat / Growth / Risk │
                 └──────────┬───────────┘
                            │
              New Evidence │
                            ▼
                 ┌──────────────────────┐
                 │ Thesis Delta Engine  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │  Valuation Engine    │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ Opportunity Engine   │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │    Option Engine     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │    Human Review      │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Human Decision     │
                 └──────────────────────┘
```

---

# 4. Layer 1 — Fact Ingestion

## 4.1 SEC Pipeline

ValuePilot should automatically monitor SEC filings every day for companies in the relevant investment universe.

Priority sources:

1. 10-K
2. 10-Q
3. earnings-related 8-K
4. earnings releases
5. investor presentations
6. earnings call transcripts
7. management Q&A
8. material 13D / 13G filings
9. relevant Form 4 insider activity
10. other material corporate filings

The first responsibility of this layer is:

> **Extract facts without making investment judgments.**

---

# 5. Financial Fact Extraction

For each reporting period, ValuePilot should extract and normalize at least:

## Income Statement

- Revenue
- Organic revenue growth
- Segment revenue
- Gross profit
- Gross margin
- Operating income
- Operating margin
- Net income
- EPS

## Cash Flow

- Operating cash flow
- CapEx
- Free cash flow
- Acquisitions
- Buybacks
- Dividends

## Balance Sheet

- Cash
- Short-term investments
- Debt
- Net debt / net cash
- Goodwill
- Intangible assets

## Shareholder Economics

- Diluted share count
- SBC
- Buybacks
- Net share-count change

## Operating Metrics

Where available:

- Customer count
- Large-customer count
- Customer concentration
- Employee count
- Revenue per employee
- bookings
- backlog
- ARR
- retention
- utilization
- pricing
- units sold
- industry-specific KPIs

## Management Guidance

Record:

- previous guidance;
- current guidance;
- guidance raised / maintained / lowered;
- management assumptions;
- important qualitative commentary.

---

# 6. Quarterly Normalization

SEC filings frequently report cumulative year-to-date numbers.

ValuePilot must normalize these into true quarterly figures.

For example:

```text
Q2 standalone cash flow
=
6M YTD cash flow
-
Q1 cash flow
```

Similarly:

```text
Q3 standalone
=
9M YTD
-
6M YTD
```

This is important for:

- FCF;
- CapEx;
- SBC;
- working capital;
- buybacks;
- acquisitions;
- cash conversion.

The system should maintain a clean historical quarterly time series.

Later analytical agents should use this database rather than repeatedly searching the internet for basic financial facts.

---

# 7. Layer 2 — Company Investment Thesis

Every tracked company should have a persistent:

```text
CompanyThesisState
```

This is one of the most important objects in ValuePilot.

It should contain several major sections.

---

# 8. Business Model

For every company, ValuePilot should answer:

1. What does the company actually sell?
2. Who is the customer?
3. Why does the customer buy?
4. How does the company get paid?
5. What are the major revenue streams?
6. Which revenue streams are most attractive?
7. What are the underlying unit economics?
8. What determines profitability?
9. What determines long-term growth?
10. What can permanently damage the business?

The objective is to understand the **economic engine**, not merely describe the company's products.

---

# 9. Moat Hypotheses

Moats should be represented as **testable hypotheses**, not simply numerical scores.

Potential moat sources include:

- switching costs;
- network effects;
- brand;
- cost advantage;
- scale advantage;
- proprietary data;
- distribution advantage;
- regulation / licensing;
- ecosystem lock-in;
- vertical domain expertise;
- installed customer relationships;
- operational complexity;
- intellectual property.

Example for EXLS:

```text
H1:
Deep integration into customer workflows creates meaningful switching costs.

H2:
Vertical domain expertise in insurance, healthcare, and banking creates
a durable competitive advantage.

H3:
Data and AI capabilities increase wallet share inside existing customers.

H4:
A meaningful portion of AI productivity gains can be retained by EXLS
rather than being passed entirely to customers.
```

Each hypothesis should have:

```text
hypothesis
confidence
supporting_evidence
contradicting_evidence
key_metrics
falsification_conditions
last_updated
```

---

# 10. Growth Hypotheses

Growth should also be represented through explicit hypotheses.

Example:

```text
H5:
EXLS can sustain organic revenue CAGR >= 10% over the next five years.

H6:
Existing customers will continue increasing wallet share.

H7:
Data/AI services can grow faster than traditional operations services.

H8:
Revenue growth can increasingly exceed employee growth.

H9:
Growth can occur without materially reducing ROIC.
```

The important question is not simply:

> How fast is the company growing?

It is:

> **Why is it growing, and how durable is that growth?**

---

# 11. Capital Allocation Hypotheses

ValuePilot should explicitly evaluate management's capital allocation.

Questions include:

- What does management do with retained earnings?
- What return does incremental reinvestment generate?
- Are acquisitions value-creating?
- Are buybacks conducted below intrinsic value?
- Is SBC economically excessive?
- Is management increasing leverage unnecessarily?
- Are dividends appropriate?
- Does management behave rationally during market dislocations?

Example hypotheses:

```text
H10:
Incremental retained earnings generate attractive returns.

H11:
Management repurchases shares primarily when the stock is below intrinsic value.

H12:
Acquisitions create economic value rather than merely increasing reported revenue.

H13:
Management maintains prudent leverage.
```

---

# 12. Risk Hypotheses

Risks should be explicit and testable.

Examples:

```text
R1: AI disrupts the traditional business model.

R2: Customers capture most AI productivity benefits through lower pricing.

R3: Customer concentration creates bargaining-power risk.

R4: Competitors weaken pricing or wallet-share growth.

R5: SBC materially dilutes owner economics.

R6: Management uses excessive leverage for buybacks or acquisitions.

R7: Growth becomes increasingly acquisition-dependent.

R8: ROIC declines as the company becomes larger.
```

---

# 13. Falsification Conditions

Every major investment thesis should answer:

> **What evidence would prove that we are wrong?**

This is essential.

Examples:

```text
If organic revenue growth falls below 7% for four consecutive quarters
without a clear cyclical explanation, reconsider the long-term growth thesis.
```

```text
If employee growth consistently equals or exceeds revenue growth while
AI-related revenue rises, reconsider the AI productivity thesis.
```

```text
If major customer losses become frequent, reconsider the switching-cost moat.
```

The system should actively search for these conditions.

This is one of the primary defenses against confirmation bias.

---

# 14. Layer 3 — Buffett / Munger Business Quality Framework

ValuePilot should analyze companies using economic principles inspired by Buffett and Munger.

The primary questions should be:

1. How does this company make money?
2. Why can customers not easily replace it?
3. Does the company possess pricing power?
4. How predictable are its economics?
5. How capital-intensive is growth?
6. What return does incremental capital generate?
7. For every $1 retained, how much future Owner Earnings can be created?
8. Does management allocate capital rationally?
9. Is the moat strengthening or weakening?
10. Will this business probably be stronger ten years from now?

These questions matter more than a single score.

---

# 15. Quality Scores

Scores can still be useful for screening and comparison.

Possible scores:

```text
Moat Score
Capital Efficiency Score
Management Score
Growth Durability Score
Financial Quality Score
Predictability Score
Overall Quality Score
```

However:

> **Scores are indexes of research, not substitutes for research.**

A score should always be traceable back to evidence and hypotheses.

---

# 16. Layer 4 — Thesis Delta Engine

This should become one of the central components of ValuePilot.

Every new:

- 10-K;
- 10-Q;
- earnings release;
- earnings call;
- investor presentation;
- material news item;

should be evaluated against the **existing thesis**.

The primary question is:

# What changed?

The engine should determine:

1. Which hypothesis is affected?
2. Is the evidence supportive, contradictory, or neutral?
3. How strong is the evidence?
4. Is the change temporary or structural?
5. Should confidence change?
6. Should valuation assumptions change?
7. Is a falsification condition closer to being triggered?

Example:

```text
Company: EXLS

Hypothesis:
H5 — Organic revenue CAGR >= 10% for five years

Previous Confidence:
75%

New Evidence:
Organic revenue growth = 14%
Management raised full-year guidance

Direction:
Positive

Magnitude:
Moderate

New Confidence:
80%
```

Another hypothesis may remain unchanged:

```text
Hypothesis:
H4 — AI productivity gains accrue meaningfully to EXLS

New Evidence:
Revenue growth remains strong,
but revenue per employee has not materially improved.

Direction:
Neutral

Conclusion:
AI productivity thesis remains unconfirmed.

Confidence:
55% → 55%
```

The system must preserve the entire history.

---

# 17. Thesis Versioning

ValuePilot should never overwrite historical investment theses.

Instead:

```text
Thesis V1
   ↓
Evidence
   ↓
Thesis V2
   ↓
Evidence
   ↓
Thesis V3
```

The system should eventually be able to answer:

> What did we believe about EXLS in August 2026?

and:

> Why did that belief change by 2028?

This creates genuine investment memory.

---

# 18. Layer 5 — Valuation State

Business quality and stock valuation must remain separate.

A great business can be a terrible investment at the wrong price.

Every company should therefore maintain a persistent:

```text
ValuationState
```

including:

- normalized Owner Earnings;
- normalized FCF;
- maintenance CapEx;
- SBC treatment;
- net cash / debt;
- diluted share count;
- base growth assumptions;
- bear growth assumptions;
- bull growth assumptions;
- discount rate;
- terminal assumptions;
- bear intrinsic value;
- base intrinsic value;
- bull intrinsic value;
- Margin-of-Safety Price;
- Put Underwriting Price.

Example:

```text
EXLS

Quality Score:
8.1 / 10

Base Intrinsic Value:
$44

Margin-of-Safety Price:
$33

Put Underwriting Price:
$31–33
```

---

# 19. Quality and Valuation Must Move Independently

For example:

```text
Quality:
8.1 → 8.2

Intrinsic Value:
$44 → $47
```

But another situation may be:

```text
Quality:
8.1 → 8.1

Intrinsic Value:
$44 → $44

Stock Price:
$46 → $31
```

Nothing changed about the company.

But the investment opportunity changed dramatically.

Therefore ValuePilot must distinguish:

```text
Business Quality
```

from:

```text
Investment Opportunity
```

---

# 20. Layer 6 — News Evidence Engine

ValuePilot should monitor authoritative news sources daily.

However, it should **not** become a news summarization product.

The primary question should always be:

> **Does this information materially change an existing investment hypothesis?**

Most news should be discarded.

---

# 21. Low-Value News

Examples:

```text
Stock rose 3% today.
```

Discard.

```text
Analyst raises target price from $42 to $45.
```

Usually discard.

```text
CEO appears at an industry conference.
```

Usually discard unless material information is disclosed.

```text
Generic AI announcement.
```

Usually discard.

---

# 22. Potentially Material News

Examples:

- major customer win;
- major customer loss;
- important pricing changes;
- new competitor;
- major product launch;
- regulatory changes;
- CEO / CFO changes;
- guidance revisions;
- significant acquisition;
- large divestiture;
- major capital allocation changes;
- structural industry changes;
- evidence of market-share gain/loss.

Each retained event should be mapped to existing hypotheses.

Example:

```text
News Event
      ↓
Relevant Hypothesis
      ↓
Supporting / Contradicting / Neutral
      ↓
Evidence Strength
      ↓
Potential Thesis Delta
```

---

# 23. Bayesian Thesis Updating

ValuePilot should conceptually operate using Bayesian thinking.

Existing thesis:

```text
Prior Belief
```

New filing / earnings / material news:

```text
New Evidence
```

Result:

```text
Updated Belief
```

This does **not** mean mechanically changing probabilities after every headline.

Confidence should move only when economically meaningful evidence appears.

Important rules:

1. Strong evidence should move confidence more than weak evidence.
2. Repeated reporting of the same event should not be double-counted.
3. Audited financial outcomes should carry more weight than management rhetoric.
4. Contradictory evidence should be surfaced prominently.
5. The system must actively search for disconfirming evidence.
6. More news does not automatically mean greater confidence.
7. Structural evidence should matter more than temporary fluctuations.

---

# 24. Anti-Confirmation-Bias Design

ValuePilot should maintain three separate evidence categories:

```text
Supporting Evidence
Contradicting Evidence
Unresolved Evidence
```

For every important thesis, the system should periodically ask:

> What is the strongest argument that this thesis is wrong?

and:

> What evidence would most change our conclusion?

This should be a first-class system feature, not an optional prompt.

---

# 25. Layer 7 — Candidate Generation

ValuePilot should eventually screen companies using accumulated research state rather than financial ratios alone.

Candidate generation should combine:

```text
Business Quality
      +
Growth Durability
      +
Thesis Confidence
      +
Valuation
      +
Margin of Safety
```

Potential candidate states:

```text
HIGH_QUALITY_COMPOUNDER

IMPROVING_BUSINESS

THESIS_UPGRADE

THESIS_DOWNGRADE

VALUATION_OPPORTUNITY

MARGIN_OF_SAFETY_OPPORTUNITY

PUT_UNDERWRITING_CANDIDATE

THESIS_CONFLICT

THESIS_BROKEN

HUMAN_REVIEW_REQUIRED
```

None of these states should automatically trigger a trade.

---

# 26. Weekly Investment Review

The weekly review should operate like an internal investment committee.

Instead of rereading dozens of filings, ValuePilot should show only meaningful changes.

The weekly review should include:

## Thesis Upgrades

Companies whose underlying business thesis strengthened.

## Thesis Downgrades

Companies where new evidence weakened the thesis.

## Valuation Opportunities

High-quality companies that entered or approached Margin-of-Safety prices.

## New Candidates

Companies that newly satisfy the required combination of:

- business quality;
- growth durability;
- thesis confidence;
- valuation;
- margin of safety.

## Thesis Conflicts

Companies where new evidence materially contradicts an important existing hypothesis.

These should receive high review priority because they may indicate that the original investment thesis is weakening.

## Falsification Alerts

Companies approaching or triggering predefined conditions that would invalidate part of the investment thesis.

Example:

```text
EXLS

Revenue Growth:
Positive

FCF:
Positive

Customer Growth:
Positive

Employee Productivity:
Unconfirmed

SBC:
Watch

Key Unresolved Question:
AI productivity economics have not yet been demonstrated clearly.

Current Action:
Human Review Required
```

The purpose of the weekly review is not to summarize everything that happened.

It is to answer:

> **What changed this week that could materially affect our investment decisions?**

---

# 27. Research Priority Engine

Not every company deserves the same amount of research time.

ValuePilot should assign research priority based on the combination of:

```text
Business Quality
        +
Magnitude of Thesis Change
        +
Valuation Attractiveness
        +
Potential Portfolio Relevance
```

For example:

```text
EXLS

Quality:
High

Thesis Change:
Positive

Valuation:
Near Margin-of-Safety Range

Portfolio Relevance:
High

Research Priority:
HIGH
```

Another company may have excellent business quality but trade far above intrinsic value:

```text
Quality:
Very High

Thesis Change:
None

Valuation:
Very Expensive

Research Priority:
LOW
```

This prevents ValuePilot from spending equal computational and human attention on every company.

The system should optimize not only capital allocation, but also:

> **Research Attention Allocation**

---

# 28. Layer 8 — Opportunity Engine

The Opportunity Engine should combine business quality and valuation.

Its purpose is not to ask:

> Is this a good company?

It should ask:

> **Is this a good company available at an attractive price today?**

Conceptually:

```text
Business Quality
        +
Growth Durability
        +
Thesis Confidence
        +
Intrinsic Value
        +
Current Market Price
        ↓
Investment Opportunity
```

Possible outputs:

```text
WATCH

RESEARCH_MORE

FAIRLY_VALUED

ATTRACTIVE

MARGIN_OF_SAFETY

EXCEPTIONAL_OPPORTUNITY
```

These are research states rather than automatic trading instructions.

---

# 29. Margin of Safety

Margin of Safety should be treated as a first-class concept.

For every company:

```text
Margin of Safety
=
1 - Market Price / Intrinsic Value
```

However, the required Margin of Safety should depend on business quality and uncertainty.

For example:

```text
Very Predictable / Wide Moat Business
Required MOS:
15–20%

Good Business / Moderate Uncertainty
Required MOS:
20–30%

Higher-Uncertainty Growth Business
Required MOS:
30–40%+

Cyclical / Difficult-to-Predict Business
Required MOS:
Potentially much larger
```

Therefore ValuePilot should not use one universal MOS threshold.

---

# 30. Intrinsic Value Is a Distribution, Not a Point Estimate

ValuePilot should avoid pretending that intrinsic value can be known precisely.

Instead of:

```text
Fair Value = $44.17
```

prefer:

```text
Bear Value:
$38

Base Value:
$44

Bull Value:
$51
```

The system should preserve the assumptions behind each scenario.

Example:

```text
Bear:
Owner Earnings Growth = 7%
Terminal Growth = 2.5%

Base:
Owner Earnings Growth = 10%
Terminal Growth = 3%

Bull:
Owner Earnings Growth = 12%
Terminal Growth = 3%
```

This allows future evidence to update assumptions rather than arbitrarily changing target prices.

---

# 31. Owner Earnings

Buffett-style valuation should emphasize economic owner earnings.

Conceptually:

```text
Owner Earnings
≈
Net Income
+ Non-Cash Charges
- Maintenance CapEx
- Required Incremental Working Capital
- Economic Cost of SBC
```

The exact calculation may differ by business model.

ValuePilot should distinguish:

```text
Reported FCF
```

from:

```text
Normalized Owner Earnings
```

For companies with substantial SBC, acquisitions, capitalized development costs, or unusual working-capital dynamics, reported FCF should not automatically be treated as owner earnings.

---

# 32. Incremental Return on Capital

One of the most important Buffett/Munger questions should be:

> **What happens to each additional dollar retained by the company?**

ValuePilot should attempt to estimate:

```text
Incremental ROIC
```

rather than relying only on historical average ROIC.

The ideal compounder has:

```text
High ROIC
        +
Large Reinvestment Runway
        +
High Incremental ROIC
```

This combination is far more valuable than high historical ROIC alone.

---

# 33. Reinvestment Runway

For long-term compounders, ValuePilot should explicitly estimate how long the company can reinvest at attractive returns.

Possible states:

```text
SHORT

MODERATE

LONG

VERY_LONG
```

The analysis should consider:

- TAM;
- market share;
- geographic expansion;
- product expansion;
- wallet-share opportunity;
- pricing power;
- competitive intensity;
- capital requirements.

This is critical because:

> A company earning 30% ROIC with nowhere to reinvest may be less valuable than a company earning 20% ROIC with a 15-year reinvestment runway.

---

# 34. Competitive Comparison Engine

A company should not be analyzed in isolation.

For every serious investment candidate, ValuePilot should identify the closest economic competitors.

The comparison should include:

```text
Revenue Growth
Organic Growth
Operating Margin
FCF Margin
ROIC
Incremental ROIC
Capital Intensity
Revenue per Employee
Customer Retention
Customer Concentration
SBC
Share Count Growth
Balance Sheet
Reinvestment Runway
Moat
Valuation
```

Example:

```text
EXLS
vs
Genpact
vs
Accenture
vs
Cognizant
```

The purpose is not merely to determine which company is larger.

The system should answer:

> **Which company owns the best business economics?**

and:

> **Why?**

---

# 35. Structural vs. Temporary Growth

Whenever a company exhibits unusually high growth, ValuePilot should explicitly investigate:

> **Is the growth structural or temporary?**

For EXLS, for example:

```text
Observed:
Revenue growth ≈ 13–15%

Question:
Why is EXLS growing approximately twice as fast as some mature peers?

Possible Explanation A:
EXLS possesses superior vertical specialization and is gaining wallet share.

Possible Explanation B:
EXLS is simply smaller and currently benefiting from a favorable growth phase.

Possible Explanation C:
Acquisitions materially inflate reported growth.

Possible Explanation D:
AI / data services are structurally accelerating the business.
```

The system should collect evidence over time to distinguish among these explanations.

This type of question should become a persistent research objective.

---

# 36. Layer 9 — Option Engine Integration

The Option Engine should sit downstream from fundamental research.

The architecture should be:

```text
Company Universe
      ↓
Quality Engine
      ↓
Growth Engine
      ↓
Thesis Engine
      ↓
Valuation Engine
      ↓
Opportunity Engine
      ↓
Option Engine
      ↓
Human Review
      ↓
Human Decision
```

The fundamental system determines:

> **Which companies are worth underwriting?**

The Option Engine determines:

> **At what strike and premium does underwriting become attractive?**

---

# 37. Put Underwriting Philosophy

Selling Put options should be treated like insurance underwriting.

The system should not begin with:

> Which Put has the highest premium?

Instead:

```text
Company Quality
      ↓
Intrinsic Value
      ↓
Margin-of-Safety Price
      ↓
Maximum Acceptable Assignment Price
      ↓
Option Market
      ↓
Premium / Risk / Return
```

The core principle is:

> **Never sell a Put at a strike where assignment would be undesirable.**

---

# 38. Put Underwriting Price

Each company should maintain:

```text
Intrinsic Value

Margin-of-Safety Price

Put Underwriting Price
```

These are different concepts.

Example:

```text
EXLS

Base Intrinsic Value:
$44

Margin-of-Safety Price:
$33

Preferred Put Underwriting Price:
$31–33
```

The Put Underwriting Price represents:

> The price at which we would be genuinely comfortable owning the business if assignment occurs.

---

# 39. Effective Assignment Price

For every Put candidate:

```text
Effective Assignment Price
=
Strike
-
Premium Received
```

Example:

```text
Strike:
$32.50

Premium:
$1.10

Effective Assignment Price:
$31.40
```

Then compare:

```text
$31.40
```

with:

```text
Intrinsic Value:
$44
```

and:

```text
MOS Price:
$33
```

This is far more important than looking at premium alone.

---

# 40. Option Candidate Evaluation

The Option Engine should evaluate:

- underlying business quality;
- thesis confidence;
- current price;
- intrinsic value;
- Margin-of-Safety Price;
- Put Underwriting Price;
- strike;
- premium;
- effective assignment price;
- DTE;
- delta;
- implied volatility;
- IV Rank where appropriate;
- bid/ask spread;
- open interest;
- volume;
- liquidity;
- return on cash / collateral;
- annualized premium yield;
- downside to intrinsic value;
- assignment risk;
- portfolio concentration.

Example:

```text
Candidate:
EXLS

Base Fair Value:
$44

MOS Price:
$33

Put Underwriting Price:
<= $32

Strike:
$32.50

Premium:
$1.10

Effective Assignment Price:
$31.40

Thesis Confidence:
High

Major Unresolved Issue:
AI productivity economics

Status:
RECOMMENDED_FOR_HUMAN_REVIEW
```

---

# 41. Option Engine Must Not Override Fundamentals

High implied volatility is not itself an investment opportunity.

The system should reject situations such as:

```text
Bad Business
+
High Premium
```

unless a separate explicitly defined strategy permits them.

For the long-term underwriting strategy, the preferred combination is:

```text
Good Business
+
Durable Growth
+
Acceptable Valuation
+
High Option Premium
```

Premium is the final filter, not the first filter.

---

# 42. Human-in-the-Loop Principle

AI responsibilities:

- maintain facts;
- maintain financial history;
- maintain company thesis;
- maintain hypotheses;
- maintain supporting evidence;
- maintain contradicting evidence;
- detect changes;
- calculate Thesis Delta;
- maintain valuation assumptions;
- calculate valuation changes;
- identify candidates;
- identify risks;
- identify falsification conditions;
- surface unresolved questions;
- rank research priorities;
- generate Put candidates.

Human responsibilities:

- decide whether the business is truly understandable;
- decide whether evidence is economically meaningful;
- approve important thesis changes when appropriate;
- determine acceptable Margin of Safety;
- judge management quality;
- decide position sizing;
- decide portfolio exposure;
- decide whether to buy;
- decide whether to sell;
- decide whether to sell Put;
- make the final investment decision.

The final investment judgment remains human.

---

# 43. Decision Audit Trail

Every material investment decision should eventually be traceable.

Example:

```text
Decision:
Sell EXLS $32.50 Put

Date:
YYYY-MM-DD

Business Thesis Version:
V7

Intrinsic Value:
$44

MOS Price:
$33

Effective Assignment Price:
$31.40

Key Supporting Evidence:
...

Key Risks:
...

Unresolved Questions:
...

Human Decision:
Approved
```

Later, ValuePilot should be able to review:

> Was the decision process good even if the investment outcome was bad?

This distinction is extremely important.

A good investment process can occasionally produce a bad outcome.

A bad process can occasionally produce a good outcome.

ValuePilot should optimize the former.

---

# 44. Investment Decision Journal

Over time, ValuePilot should maintain an investment decision journal.

It should record:

```text
What we believed

What we expected

What could prove us wrong

What price we considered attractive

What decision we made

What actually happened

What we learned
```

This enables systematic postmortems.

---

# 45. Outcome vs. Process Review

When reviewing historical investments, ValuePilot should distinguish:

```text
Decision Quality
```

from:

```text
Investment Outcome
```

Possible classification:

```text
Good Process + Good Outcome

Good Process + Bad Outcome

Bad Process + Good Outcome

Bad Process + Bad Outcome
```

The most dangerous category is:

```text
Bad Process + Good Outcome
```

because it can reinforce poor investment behavior.

---

# 46. Long-Term Strategic Asset

The most valuable asset ValuePilot can build is not:

- the LLM;
- the SEC parser;
- the news API;
- the option-chain provider;
- the financial database.

The most valuable asset is:

# Company Thesis Database

Over many years, it should contain the accumulated intellectual history of every important company.

For example, ValuePilot should eventually answer:

> Why did we first become interested in EXLS?

> What did we believe about its moat in 2026?

> Why did we believe revenue could grow more than 10%?

> Which quarters strengthened that conclusion?

> Which evidence contradicted it?

> When did we change the long-term growth assumption?

> Why did intrinsic value move from $44 to $51?

> What evidence would have caused us to abandon the thesis?

> At what historical prices did the stock enter our Margin-of-Safety range?

> Which Put contracts offered attractive underwriting opportunities?

This creates genuine institutional memory.

---

# 47. Development Philosophy

Do **not** begin by building a massive SEC/news ingestion system.

The correct order is:

> **Build the memory and reasoning structure first.**

Otherwise ValuePilot will become:

```text
Huge Amount of Information
          +
LLM Summaries
          =
More Noise
```

Instead:

```text
Structured Thesis
        +
Relevant Evidence
        +
Persistent Memory
        =
Better Decisions
```

---

# 48. Development Roadmap

## Phase 1 — Thesis Foundation

Build the core investment-memory model first.

### Tasks

1. Define `CompanyThesisState`.
2. Define `InvestmentHypothesis`.
3. Define `RiskHypothesis`.
4. Define `FalsificationCondition`.
5. Define `ThesisEvidence`.
6. Define `ThesisDelta`.
7. Define evidence-strength semantics.
8. Define confidence semantics.
9. Implement thesis versioning.
10. Implement supporting / contradicting / unresolved evidence.

This is the highest-priority phase.

---

# 49. Phase 2 — Financial State

Build normalized company financial history.

### Tasks

1. Quarterly financial normalization.
2. Income statement history.
3. Cash-flow history.
4. Balance-sheet history.
5. Share-count history.
6. SBC history.
7. Buyback history.
8. Debt history.
9. Segment history.
10. Relevant operating KPIs.

---

# 50. Phase 3 — Buffett / Munger Quality Engine

Build the business-quality framework.

### Tasks

1. Business-model representation.
2. Moat hypotheses.
3. Pricing-power analysis.
4. Capital-intensity analysis.
5. ROIC.
6. Incremental ROIC.
7. Reinvestment runway.
8. Owner Earnings.
9. Management capital allocation.
10. Growth durability.
11. Business predictability.
12. Quality scores.

Scores must remain explainable through underlying evidence.

---

# 51. Phase 4 — Valuation Engine

Build persistent valuation state.

### Tasks

1. Normalized Owner Earnings.
2. Bear / Base / Bull scenarios.
3. DCF.
4. Multiple-based sanity checks.
5. Reverse DCF.
6. Margin-of-Safety Price.
7. Put Underwriting Price.
8. Valuation versioning.
9. Assumption history.
10. Valuation Delta.

---

# 52. Phase 5 — SEC / Earnings Automation

Only after the thesis structure exists should ingestion become highly automated.

### Tasks

1. Daily SEC filing detection.
2. Filing classification.
3. Filing prioritization.
4. Structured financial extraction.
5. Earnings-release ingestion.
6. Investor-presentation ingestion.
7. Earnings-call ingestion.
8. Management Q&A extraction.
9. Guidance extraction.
10. Compare new facts with previous state.
11. Generate Thesis Delta.

---

# 53. Phase 6 — News Evidence Engine

### Tasks

1. Ingest authoritative news sources.
2. Deduplicate events.
3. Detect repeated reporting of the same event.
4. Filter immaterial information.
5. Identify relevant hypotheses.
6. Classify evidence.
7. Search for contradicting evidence.
8. Estimate evidence strength.
9. Generate material-change alerts.
10. Avoid unnecessary thesis updates.

The objective is:

> **Signal extraction, not news consumption.**

---

# 54. Phase 7 — Weekly Investment Committee

Build the weekly review system.

Output should include:

```text
THESIS UPGRADES

THESIS DOWNGRADES

NEW HIGH-QUALITY COMPANIES

VALUATION OPPORTUNITIES

MARGIN-OF-SAFETY OPPORTUNITIES

THESIS CONFLICTS

FALSIFICATION ALERTS

HIGH-PRIORITY RESEARCH QUESTIONS

PUT UNDERWRITING CANDIDATES
```

The investor should be able to review the important changes without rereading all source material.

---

# 55. Phase 8 — Opportunity Engine

Combine:

```text
Quality
+
Growth
+
Thesis Confidence
+
Valuation
+
Margin of Safety
```

to identify companies requiring human attention.

The system should rank opportunities rather than automatically trade them.

---

# 56. Phase 9 — Option Integration

Feed approved fundamental candidates into the Option Engine.

### Tasks

1. Retrieve option chains.
2. Filter by liquidity.
3. Calculate effective assignment price.
4. Compare assignment price with intrinsic value.
5. Compare assignment price with MOS Price.
6. Calculate premium yield.
7. Calculate annualized return on collateral.
8. Analyze delta / IV / DTE.
9. Evaluate portfolio exposure.
10. Rank Put contracts.
11. Require explicit human confirmation.

---

# 57. Phase 10 — Decision Journal and Learning Loop

Once the system has accumulated decisions, ValuePilot should learn from the investment process.

The loop becomes:

```text
Research
   ↓
Thesis
   ↓
Valuation
   ↓
Opportunity
   ↓
Human Decision
   ↓
Investment Outcome
   ↓
Postmortem
   ↓
Process Improvement
```

The purpose is not to train the system to chase whatever happened to work.

Instead, ValuePilot should distinguish between:

```text
Good Process + Good Outcome

Good Process + Bad Outcome

Bad Process + Good Outcome

Bad Process + Bad Outcome
```

The most dangerous case is:

```text
Bad Process + Good Outcome
```

because a profitable outcome can reinforce poor investment behavior.

The system should therefore evaluate:

> **Was the original decision rational given the information available at the time?**

rather than:

> **Did the stock subsequently go up?**

---

# 58. Investment Decision Record

Every meaningful investment decision should create a persistent record.

Example:

```text
Decision ID:
EXLS-2026-001

Company:
EXLS

Decision Date:
YYYY-MM-DD

Decision Type:
SELL_PUT

Thesis Version:
V7

Business Quality:
8.1 / 10

Thesis Confidence:
High

Base Intrinsic Value:
$44

Bear Intrinsic Value:
$38

Bull Intrinsic Value:
$51

Margin-of-Safety Price:
$33

Put Underwriting Price:
$31–33

Selected Strike:
$32.50

Premium:
$1.10

Effective Assignment Price:
$31.40

Key Supporting Evidence:
- Organic revenue growth remains above 10%.
- FCF generation remains strong.
- Customer relationships appear sticky.
- Data/AI business continues gaining share.

Key Contradicting Evidence:
- AI productivity economics remain unconfirmed.
- SBC remains meaningful.
- Leverage has increased.

Falsification Conditions:
- Sustained organic growth below threshold.
- Major customer losses.
- Material deterioration in incremental ROIC.
- Evidence that AI productivity benefits accrue primarily to customers.

Human Decision:
APPROVED
```

This record should never be rewritten using hindsight.

It represents:

> **What we knew and believed at the moment the decision was made.**

---

# 59. Postmortem Review

After sufficient time has passed, ValuePilot should compare the original decision with subsequent reality.

The postmortem should answer:

1. What did we expect?
2. What actually happened?
3. Which assumptions were correct?
4. Which assumptions were wrong?
5. Which risks materialized?
6. Which risks did not materialize?
7. Did the moat strengthen or weaken?
8. Did management allocate capital as expected?
9. Did Owner Earnings develop as expected?
10. Was our valuation model reasonable?
11. Was the Margin of Safety sufficient?
12. Was the position size appropriate?
13. Was the Put underwriting price appropriate?
14. Did we ignore contradictory evidence?
15. What should change in our future process?

The goal is not merely to review the company.

It is to review:

> **our investment reasoning process.**

---

# 60. Thesis Calibration

Over time, ValuePilot should measure how well its thesis confidence levels correspond to reality.

For example, if hypotheses classified as:

```text
HIGH CONFIDENCE
```

frequently fail, the system is overconfident.

Likewise, if:

```text
LOW CONFIDENCE
```

hypotheses repeatedly prove correct, the confidence framework may be too conservative.

Eventually ValuePilot should be able to analyze:

```text
Hypothesis Confidence
        ↓
Subsequent Evidence
        ↓
Calibration Accuracy
```

This allows the investment research process itself to improve.

---

# 61. Valuation Calibration

ValuePilot should also evaluate historical valuation assumptions.

For each company, compare:

```text
Original Growth Assumption
Original Margin Assumption
Original Owner Earnings
Original ROIC Assumption
Original Intrinsic Value
```

with subsequent reality.

Example:

```text
EXLS — 2026 Base Case

Expected 5Y Revenue CAGR:
10%

Actual:
12.1%

Expected Operating Margin:
16%

Actual:
17.4%

Expected Owner Earnings:
$X

Actual:
$Y
```

The purpose is to determine whether ValuePilot systematically:

- overestimates growth;
- underestimates growth;
- overestimates margins;
- underestimates capital requirements;
- ignores dilution;
- overestimates terminal value;
- uses insufficient Margin of Safety.

This creates a feedback loop for valuation discipline.

---

# 62. Research Error Taxonomy

Investment mistakes should be classified.

Possible categories:

```text
BUSINESS_MODEL_ERROR

MOAT_ERROR

GROWTH_DURABILITY_ERROR

MANAGEMENT_ERROR

CAPITAL_ALLOCATION_ERROR

VALUATION_ERROR

CYCLICALITY_ERROR

BALANCE_SHEET_ERROR

POSITION_SIZING_ERROR

TIMING_ERROR

CONFIRMATION_BIAS

INFORMATION_QUALITY_ERROR

OPTION_UNDERWRITING_ERROR

UNKNOWN_UNKNOWN
```

For every major mistake, ValuePilot should ask:

> **Was this error preventable?**

If yes:

> **What process change would reduce the probability of repeating it?**

---

# 63. Research Question Queue

ValuePilot should maintain unresolved questions for every important company.

Example:

```text
EXLS — Open Research Questions

Q1:
Why is EXLS growing materially faster than Genpact?

Q2:
Is the growth advantage structural or primarily a function of smaller scale?

Q3:
Are AI productivity gains improving revenue per employee?

Q4:
How much of AI productivity improvement is retained by EXLS versus passed to customers?

Q5:
Is wallet-share expansion measurable?

Q6:
Are customer switching costs actually increasing?

Q7:
Can EXLS maintain double-digit organic growth at $4B–$5B revenue?

Q8:
Is management creating value through buybacks after considering SBC and leverage?
```

These questions should persist across quarters.

When new evidence arrives, ValuePilot should attempt to answer them.

Questions should be closed only when sufficient evidence exists.

---

# 64. Company Research Dashboard

Each serious company should eventually have a single research dashboard.

Example:

```text
==================================================
EXLS — INVESTMENT DASHBOARD
==================================================

BUSINESS QUALITY
8.1 / 10

MOAT
7.0 / 10
Trend: Stable / Improving

GROWTH DURABILITY
8.5 / 10
Trend: Improving

CAPITAL EFFICIENCY
High

BALANCE SHEET
Healthy
Watch: Increasing leverage

THESIS CONFIDENCE
High

--------------------------------------------------

VALUATION

Bear Value:
$38

Base Value:
$44

Bull Value:
$51

MOS Price:
$33

Put Underwriting Price:
$31–33

Current Price:
$XX

--------------------------------------------------

THESIS CHANGES

Last Quarter:
Positive

Last 12 Months:
Positive

--------------------------------------------------

KEY SUPPORTING EVIDENCE

1. Double-digit organic revenue growth.
2. Strong FCF generation.
3. Increasing Data/AI contribution.
4. Customer relationships remain sticky.

--------------------------------------------------

KEY CONTRADICTING EVIDENCE

1. AI productivity economics remain unproven.
2. SBC remains meaningful.
3. Leverage has increased.

--------------------------------------------------

OPEN QUESTIONS

1. Why is EXLS growing faster than Genpact?
2. Can growth remain >10% at larger scale?
3. Who captures AI productivity economics?

--------------------------------------------------

FALSIFICATION WATCH

No major condition currently triggered.

--------------------------------------------------

OPPORTUNITY STATUS

WATCH / ATTRACTIVE / MOS / PUT_CANDIDATE

==================================================
```

This should become the primary interface for human investment review.

---

# 65. Portfolio-Level View

Company analysis alone is not enough.

ValuePilot should eventually understand portfolio-level exposure.

For example:

```text
Portfolio Exposure

AI Infrastructure:
18%

Financial Services:
12%

Software:
15%

Healthcare:
8%

Consumer:
10%

Cyclical:
15%

Other:
22%
```

It should also detect hidden correlations.

For example:

```text
EXLS
ACN
CTSH
Genpact
```

may appear to be four separate companies but could share exposure to:

- enterprise IT spending;
- outsourcing budgets;
- labor costs;
- AI disruption;
- financial-services customers.

Therefore portfolio risk should consider:

> **Economic exposure**

rather than ticker count alone.

---

# 66. Position Sizing

Position sizing should remain a human decision, but ValuePilot should provide structured support.

Inputs may include:

```text
Business Quality

Thesis Confidence

Margin of Safety

Downside Risk

Balance Sheet Risk

Cyclicality

Portfolio Correlation

Liquidity

Existing Exposure
```

Conceptually:

```text
Higher Quality
+
Higher Confidence
+
Larger Margin of Safety
+
Lower Portfolio Correlation
        ↓
Potentially Larger Position
```

But the final position size remains explicitly human-approved.

---

# 67. Source Hierarchy

ValuePilot should maintain a strict evidence hierarchy.

Preferred sources:

## Tier 1 — Primary Sources

- SEC filings;
- audited financial statements;
- company earnings releases;
- investor presentations;
- earnings calls;
- regulatory filings.

## Tier 2 — High-Quality Independent Sources

- reputable financial news organizations;
- industry publications;
- government data;
- credible market research.

## Tier 3 — Secondary Analysis

- analyst research;
- specialist commentary;
- high-quality investor analysis.

## Tier 4 — Weak Evidence

- social media;
- unsourced commentary;
- promotional content;
- anonymous claims.

The system should record the source quality of every material piece of evidence.

A management claim should not automatically be treated as a verified fact.

---

# 68. Fact vs. Interpretation

ValuePilot must explicitly distinguish:

```text
FACT
```

from:

```text
INTERPRETATION
```

Example:

```text
FACT:
EXLS organic revenue grew 14%.

INTERPRETATION:
EXLS may be gaining wallet share.

HYPOTHESIS:
EXLS has a structural competitive advantage that allows it
to grow materially faster than peers.
```

These are three different levels of knowledge.

The database should never collapse them into one field.

---

# 69. Evidence Provenance

Every important conclusion should be traceable to evidence.

Conceptually:

```text
Conclusion
    ↓
Hypothesis
    ↓
Evidence
    ↓
Source
    ↓
Original Document
```

For example:

```text
EXLS Growth Durability = HIGH
        ↓
H5: Organic growth can remain >=10%
        ↓
2026 Q2 organic growth = 14%
        ↓
EXLS 2026 Q2 10-Q
        ↓
SEC accession number
```

This makes the research auditable.

---

# 70. Evidence Deduplication

The same event may appear in:

- SEC filing;
- earnings release;
- Reuters article;
- Bloomberg article;
- analyst note;
- social media.

ValuePilot must recognize that these may represent:

> **one underlying event**

rather than six independent pieces of evidence.

Evidence should therefore have an:

```text
event_id
```

Multiple sources may attach to the same event.

This prevents Bayesian confidence from being artificially inflated through duplicated reporting.

---

# 71. Materiality Filter

The system should aggressively filter information.

A useful conceptual rule:

```text
Does this information have a reasonable probability of changing:

Business Quality?

Growth Durability?

Moat?

Capital Allocation?

Valuation?

Risk?

Falsification Condition?
```

If the answer is:

```text
NO
```

the information normally should not enter the active thesis-update workflow.

This prevents information overload.

---

# 72. Alert Philosophy

ValuePilot should not maximize the number of alerts.

It should maximize:

> **Signal-to-Noise Ratio**

Good alerts:

```text
EXLS entered Margin-of-Safety range.

EXLS guidance materially raised.

EXLS lost a Top-10 customer.

EXLS incremental ROIC deteriorated.

EXLS thesis falsification condition triggered.

EXLS $32.50 Put now offers effective assignment price below underwriting value.
```

Bad alerts:

```text
EXLS moved 2%.

Analyst reiterated Buy.

EXLS mentioned AI at a conference.

EXLS trading volume increased.
```

unless such information is relevant to a specific trading strategy.

---

# 73. Daily Workflow

The automated daily workflow should eventually resemble:

```text
1. Scan tracked SEC filings.

2. Detect earnings releases / investor presentations.

3. Retrieve relevant earnings-call information.

4. Normalize new financial facts.

5. Compare new facts with historical state.

6. Generate potential Thesis Delta.

7. Scan authoritative news.

8. Deduplicate events.

9. Discard immaterial information.

10. Map material evidence to existing hypotheses.

11. Search for contradictory evidence.

12. Detect valuation opportunities.

13. Detect Margin-of-Safety opportunities.

14. Detect Put underwriting opportunities.

15. Generate Human Review Queue.
```

The objective is not to produce a large daily report.

The ideal daily output may contain only a few items.

---

# 74. Weekly Workflow

Once per week:

```text
1. Review Thesis Upgrades.

2. Review Thesis Downgrades.

3. Review Thesis Conflicts.

4. Review Falsification Alerts.

5. Review companies entering MOS ranges.

6. Review new high-quality candidates.

7. Review major valuation changes.

8. Review unresolved research questions.

9. Review Put underwriting candidates.

10. Human approves / rejects important thesis changes.
```

The weekly review should become the investor's main research-management workflow.

---

# 75. Quarterly Workflow

After earnings season, ValuePilot should conduct a deeper review.

For each important company:

```text
Financial Trend
Moat Trend
Growth Trend
ROIC Trend
Owner Earnings Trend
Capital Allocation
Competitive Position
Management Credibility
Valuation
Open Questions
Falsification Conditions
```

Then ask:

> **Is this business stronger, weaker, or essentially unchanged from one year ago?**

This is more important than whether quarterly EPS beat consensus.

---

# 76. Annual Deep Review

At least once per year, important holdings and high-priority watchlist companies should receive a complete thesis review.

The annual review should temporarily ignore the current stock price and ask:

> If we did not already own or follow this company, would we still want to study it today?

Then rebuild the strongest:

```text
Bull Case

Bear Case
```

and compare both with the existing thesis.

The objective is to prevent thesis inertia.

---

# 77. AI Agent Boundaries

Different agents should have clearly separated responsibilities.

Possible architecture:

```text
SEC Agent
    ↓
Fact Extraction

Financial Agent
    ↓
Normalization / Metrics

Business Analyst Agent
    ↓
Business Model / Economics

Thesis Agent
    ↓
Hypothesis Maintenance

Skeptic Agent
    ↓
Contradicting Evidence / Bear Case

Valuation Agent
    ↓
Intrinsic Value

News Evidence Agent
    ↓
Material Event Detection

Opportunity Agent
    ↓
Candidate Ranking

Option Agent
    ↓
Put Underwriting Analysis
```

No single agent should control the entire reasoning chain without checks.

---

# 78. Skeptic Agent

A dedicated skeptical / red-team function should be a first-class component.

For every major thesis update, it should ask:

1. What is the strongest alternative explanation?
2. What evidence contradicts the conclusion?
3. Are we confusing correlation with causation?
4. Are we extrapolating temporary growth?
5. Are management incentives distorting the narrative?
6. Are accounting metrics overstating economics?
7. Are we underestimating competition?
8. What would a short seller argue?
9. What evidence would most reduce confidence?
10. Are we becoming emotionally attached to the company?

This is an important protection against automated confirmation bias.

---

# 79. Human Approval Boundaries

Human approval should be required for:

```text
Major Thesis Change

Thesis Broken

Material Intrinsic Value Change

Company Promotion to Core Candidate

Company Removal from Core Candidate List

Position Sizing

Buy Decision

Sell Decision

Sell Put Decision

Any Live Trade
```

AI may recommend review.

AI does not make the final decision.

---

# 80. Data Model Principle

The database should preserve four distinct layers:

```text
FACT

EVIDENCE

HYPOTHESIS

DECISION
```

Do not merge them.

Conceptually:

```text
FACT
  ↓
becomes
EVIDENCE
  ↓
supports or contradicts
HYPOTHESIS
  ↓
influences
VALUATION / OPPORTUNITY
  ↓
supports
HUMAN DECISION
```

This separation should guide the database schema.

---

# 81. Historical Reproducibility

ValuePilot should eventually be able to reconstruct the system state at any historical date.

For example:

> Show me everything we knew about EXLS on August 20, 2026.

The result should include:

```text
Financial Data Available at the Time

Thesis Version

Evidence Available at the Time

Intrinsic Value Estimate

Market Price

Open Questions

Risk Assessment

Human Decisions
```

Future information must not leak backward into historical analysis.

This is critical for honest investment postmortems.

---

# 82. Avoid Hindsight Bias

Historical reviews must use:

> **information available at the time**

rather than later knowledge.

Otherwise every mistake looks obvious in hindsight.

ValuePilot should preserve timestamps for:

- facts;
- evidence;
- hypotheses;
- valuations;
- decisions.

This enables proper decision-quality evaluation.

---

# 83. Core Success Metrics

ValuePilot should not primarily measure success by:

```text
Number of filings processed

Number of news articles analyzed

Number of AI reports generated

Number of trading signals
```

Better success metrics include:

```text
Percentage of material events detected

False-positive alert rate

Percentage of thesis changes with traceable evidence

Research time saved

Quality of valuation calibration

Confidence calibration

Frequency of repeated investment mistakes

Quality of candidate ranking

Decision-process consistency
```

Ultimately:

> **Does ValuePilot help the investor make better decisions over time?**

---

# 84. What ValuePilot Should Not Become

ValuePilot should not become:

## A News Aggregator

More information is not necessarily better information.

## A Target-Price Generator

False precision is dangerous.

## A Black-Box Stock Ranking Model

Scores without explanations are not useful enough.

## An Autonomous Trading Bot

The objective is decision support.

## An LLM Opinion Machine

The system should maintain evidence and reasoning history.

## A Confirmation-Bias Machine

Contradictory evidence must be actively sought.

---

# 85. What ValuePilot Should Become

ValuePilot should become:

# A Persistent Investment Intelligence System

with:

```text
Memory

Evidence

Business Understanding

Thesis

Skepticism

Valuation

Opportunity Detection

Decision Support

Learning
```

Its purpose is to create a disciplined loop:

```text
Observe
   ↓
Understand
   ↓
Form Hypothesis
   ↓
Collect Evidence
   ↓
Challenge Hypothesis
   ↓
Update Thesis
   ↓
Update Valuation
   ↓
Detect Opportunity
   ↓
Human Decision
   ↓
Observe Outcome
   ↓
Learn
   ↓
Repeat
```

---

# 86. The Company Thesis Database Is the Core Asset

The most important long-term asset in ValuePilot should be the:

# Company Thesis Database

Raw financial data can be purchased.

SEC filings are public.

News is widely available.

LLMs will continue to improve and become cheaper.

Option-chain data can be obtained from many providers.

Those things are necessary infrastructure, but they are not the durable intellectual asset.

The durable asset is the accumulated history of:

```text
What we believed

Why we believed it

What evidence supported it

What evidence contradicted it

What remained uncertain

What would prove us wrong

How the thesis changed

How valuation changed

What decisions we made

What happened afterward

What we learned
```

After several years, this database should represent the accumulated investment knowledge of ValuePilot.

---

# 87. Example — EXLS Thesis Evolution

A mature ValuePilot system should eventually be able to reconstruct something like:

```text
==================================================
EXLS THESIS HISTORY
==================================================

2026-08

Initial Thesis:

EXLS appears to be a high-quality,
asset-light business-process and
data/AI services company.

Key Positive Hypotheses:

H1:
Customer workflow integration creates
meaningful switching costs.

H2:
Vertical specialization creates
competitive advantages.

H3:
Data/AI capabilities increase wallet share.

H4:
AI productivity gains may improve
economic returns.

H5:
Organic revenue can compound at >=10%
for the next five years.

Key Risks:

R1:
AI productivity benefits may accrue
primarily to customers.

R2:
Growth may slow materially as EXLS scales.

R3:
Competition from Genpact, Accenture,
Cognizant and others may limit returns.

R4:
SBC may reduce true Owner Earnings.

R5:
Increasing leverage may weaken
capital-allocation quality.

Base Intrinsic Value:
$44

MOS Price:
$33

Put Underwriting Price:
$31–33
```

Then later:

```text
2026 Q3

New Evidence:

Organic growth:
Strong

Guidance:
Raised

Revenue per employee:
Improving slightly

Customer concentration:
Stable

SBC:
Still elevated

Thesis Delta:

H5:
Confidence increased.

H4:
Some supporting evidence,
but still insufficient.

R4:
Unchanged.

Intrinsic Value:
$44 → $46
```

Later:

```text
2027 Q2

New Evidence:

Revenue growth:
12%

Employee growth:
6%

Operating margin:
Expanding

Major insurance client:
Expanded relationship

Thesis Delta:

H1:
Strengthened

H3:
Strengthened

H4:
Strengthened materially

Growth Durability:
Higher confidence

Intrinsic Value:
$46 → $51
```

Or the opposite may occur:

```text
2028 Q1

New Evidence:

Organic growth:
6%

Large customer:
Lost

Pricing:
Under pressure

Revenue per employee:
Flat

Thesis Delta:

H1:
Weakened

H4:
Weakened

H5:
Falsification condition approaching

Intrinsic Value:
$51 → $39

Status:
THESIS_CONFLICT

Human Review:
Required
```

This historical chain is far more valuable than a collection of quarterly AI reports.

---

# 88. Investment Knowledge Compounding

ValuePilot itself should compound knowledge in a way similar to capital.

The process is:

```text
Company Research
      ↓
Structured Knowledge
      ↓
Historical Evidence
      ↓
Better Pattern Recognition
      ↓
Better Questions
      ↓
Better Decisions
      ↓
Better Postmortems
      ↓
Improved Research Framework
      ↓
Better Future Research
```

The objective is therefore not merely:

> Find the next stock.

It is:

> **Build an investment process that becomes better every year.**

---

# 89. Cross-Company Learning

The thesis database should eventually allow ValuePilot to learn across companies.

For example, after studying:

```text
EXLS
Genpact
Accenture
Cognizant
EPAM
```

ValuePilot should develop better understanding of:

```text
IT Services Economics

BPO Economics

AI Productivity

Revenue per Employee

Customer Switching Costs

Offshore Labor Economics

Pricing Power

Vertical Specialization

Scale Effects
```

Then when a new company enters the universe, ValuePilot should be able to compare it with existing economic patterns.

The system should ask:

> Which companies have we studied before that have similar economics?

This creates reusable investment knowledge.

---

# 90. Industry Thesis Database

In addition to company theses, ValuePilot should eventually maintain:

```text
IndustryThesisState
```

Examples:

```text
AI Infrastructure

Data Centers

Semiconductors

Insurance

Payment Networks

IT Services / BPO

Cloud Software

Healthcare Services

Industrial Power

Consumer Retail
```

An industry thesis could contain:

```text
Industry Structure

Major Competitors

Capital Intensity

Pricing Power

Cyclicality

Supply / Demand

Regulatory Environment

Technology Disruption

Industry ROIC

Key Growth Drivers

Key Risks

Leading Indicators
```

This allows company analysis to inherit industry context.

---

# 91. Company Thesis vs. Industry Thesis

The system should distinguish:

```text
Industry Tailwind
```

from:

```text
Company Competitive Advantage
```

A company may grow because the entire industry is growing.

That does not necessarily mean it has a moat.

Conceptually:

```text
Company Growth
=
Industry Growth
+
Market Share Change
+
Pricing
+
Product Expansion
+
Acquisitions
```

ValuePilot should attempt to decompose growth into these components.

This is important when determining whether superior growth is structural.

---

# 92. Market Share Analysis

For serious candidates, ValuePilot should attempt to answer:

> Is the company actually gaining market share?

If:

```text
Company Organic Growth:
14%

Industry Growth:
6%
```

then there may be evidence of:

```text
Market Share Gain
```

But the system should investigate why.

Possible causes:

```text
Better Product

Better Distribution

Lower Price

Better Customer Service

Superior Technology

Acquisitions

Temporary Customer Wins

Competitor Weakness

Structural Competitive Advantage
```

Market-share gains should not automatically be classified as moat expansion.

---

# 93. Competitive Advantage Period

Valuation should explicitly consider:

# Competitive Advantage Period

The important question is not merely:

> Does the company have a moat?

It is:

> **How long can excess economic returns persist?**

Possible states:

```text
NO_MOAT

SHORT
3–5 years

MODERATE
5–10 years

LONG
10–20 years

VERY_LONG
20+ years
```

This should influence valuation assumptions.

A company with a long Competitive Advantage Period can justify a much larger portion of value coming from future cash flows.

---

# 94. Moat Trend

Moat should not be treated as static.

ValuePilot should maintain:

```text
Moat Strength

Moat Trend
```

Possible trends:

```text
STRENGTHENING

STABLE

WEAKENING

UNCERTAIN
```

Example:

```text
Company:
EXLS

Moat Strength:
7 / 10

Moat Trend:
STRENGTHENING

Evidence:

Increasing wallet share

Higher-value Data/AI services

Longer customer relationships

Improving revenue per employee
```

Or:

```text
Moat Trend:
WEAKENING

Evidence:

Customer losses

Pricing pressure

Falling retention

Competitors gaining share
```

Trend may be more important than the absolute moat score.

---

# 95. Management Credibility Tracking

Management guidance should not simply be recorded.

ValuePilot should track management credibility over time.

For example:

```text
Guidance Issued
      ↓
Actual Result
      ↓
Accuracy
```

Track:

```text
Revenue Guidance Accuracy

Margin Guidance Accuracy

FCF Guidance Accuracy

CapEx Guidance Accuracy

Acquisition Synergy Accuracy

Long-Term Target Accuracy
```

Management that repeatedly:

```text
Promises Less
Delivers More
```

deserves greater credibility than management that consistently overpromises.

---

# 96. Management Capital Allocation Scorecard

For each CEO / management team, maintain a historical scorecard.

Evaluate:

```text
Organic Reinvestment

Acquisitions

Buybacks

Dividends

Debt

SBC

Asset Sales
```

For buybacks, ask:

> Were shares repurchased below intrinsic value?

For acquisitions:

> Did acquired capital subsequently earn an attractive return?

For debt:

> Was leverage used prudently?

This should create a long-term capital-allocation record.

---

# 97. SBC Treatment

Stock-based compensation must be treated as an economic cost.

ValuePilot should not blindly accept:

```text
Adjusted EPS
```

that excludes SBC.

The system should track:

```text
SBC / Revenue

SBC / FCF

SBC / Net Income

Gross Buybacks

Net Buybacks

Diluted Share Count Change
```

A company that reports:

```text
$500M Buybacks
```

but issues:

```text
$450M of SBC
```

is economically very different from a company genuinely shrinking its share count.

The relevant metric is:

> **Net change in owner share of the business.**

---

# 98. Buyback Quality

Buybacks should be evaluated against intrinsic value.

Possible classifications:

```text
VALUE_CREATING

NEUTRAL

VALUE_DESTROYING

UNCERTAIN
```

Example:

```text
Intrinsic Value:
$50

Average Buyback Price:
$35

Classification:
VALUE_CREATING
```

versus:

```text
Intrinsic Value:
$50

Average Buyback Price:
$75

Classification:
VALUE_DESTROYING
```

This turns buyback analysis into capital-allocation analysis rather than simply recording cash returned to shareholders.

---

# 99. Acquisition Quality

For acquisitive companies, ValuePilot should maintain acquisition cohorts.

Example:

```text
Acquisition:
Company A

Date:
2026

Purchase Price:
$500M

Expected Revenue:
$100M

Expected Synergies:
$30M
```

Then review later:

```text
Actual Revenue

Actual Margin

Actual Synergies

Incremental FCF

Incremental ROIC
```

This allows ValuePilot to determine whether management has historically created value through acquisitions.

---

# 100. Growth Quality

Not all revenue growth is equal.

ValuePilot should distinguish:

```text
Organic Growth

Price Growth

Volume Growth

Acquisition Growth

FX Growth

Share-Count Effects
```

Preferred growth is generally:

```text
Organic
+
High Incremental ROIC
+
Low Capital Requirements
```

Growth that requires:

```text
Large Acquisitions
+
Increasing Debt
+
Heavy SBC
```

should receive a lower quality assessment.

---

# 101. EPS Growth Decomposition

EPS growth should be decomposed.

Conceptually:

```text
EPS Growth
≈
Revenue Growth
+
Margin Expansion
+
Share Count Reduction
+
Financial Leverage Effects
```

This helps distinguish:

```text
High-Quality EPS Growth
```

from:

```text
Financially Engineered EPS Growth
```

Example:

```text
Revenue:
+12%

Margin:
+1%

Share Count:
-4%

EPS:
+18%
```

ValuePilot should understand where the 18% came from.

---

# 102. Growth Durability

For each growth driver, maintain:

```text
Growth Driver

Estimated Duration

Confidence

Evidence
```

Example:

```text
EXLS

Growth Driver:
Data/AI wallet-share expansion

Duration:
5–10 years

Confidence:
Medium-High
```

Another:

```text
Growth Driver:
Temporary pricing increase

Duration:
1–2 years

Confidence:
High
```

Long-term valuation should emphasize durable drivers rather than temporary ones.

---

# 103. Expectations Investing

ValuePilot should eventually compare:

```text
What the Business Can Deliver
```

with:

```text
What the Market Price Already Implies
```

This is critical.

A great company can be a poor investment if the market assumes unrealistic growth.

Therefore ValuePilot should support:

# Reverse DCF

Instead of only asking:

> What is the company worth?

also ask:

> **What assumptions must be true to justify today's market price?**

Example:

```text
Current Price:
$60

Implied Requirement:
Owner Earnings CAGR of 15% for 10 years
```

Then compare with:

```text
Our Base Case:
10%
```

This immediately reveals expectation risk.

---

# 104. Opportunity = Quality × Price × Expectations

A useful conceptual framework is:

```text
Investment Opportunity
=
Business Quality
×
Difference Between Reality and Market Expectations
×
Margin of Safety
```

The best opportunity is not necessarily:

```text
Highest Growth Company
```

or:

```text
Cheapest Company
```

It is often:

> **A high-quality business where market expectations are materially below probable economic reality.**

---

# 105. Watchlist Architecture

The watchlist should not be one undifferentiated list.

Possible states:

```text
DISCOVERY

RESEARCHING

QUALIFIED

HIGH_QUALITY

WAIT_FOR_PRICE

MOS_CANDIDATE

PUT_CANDIDATE

OWNED

THESIS_CONFLICT

EXIT_REVIEW

REJECTED
```

A company should move through states based on research and valuation.

Example:

```text
EXLS

DISCOVERY
   ↓
RESEARCHING
   ↓
HIGH_QUALITY
   ↓
WAIT_FOR_PRICE
   ↓
PUT_CANDIDATE
```

This makes the research process explicit.

---

# 106. Rejected Company Database

ValuePilot should preserve rejected companies.

Do not simply delete them.

Record:

```text
Company

Date Rejected

Reason

Thesis

Valuation

Key Risks

Conditions for Reconsideration
```

Example:

```text
Company:
XYZ

Rejected Because:
Weak moat and excessive capital intensity.

Reconsider If:
ROIC improves materially and customer retention strengthens.
```

A rejected company may later become interesting.

Historical rejection reasoning is valuable.

---

# 107. Opportunity History

ValuePilot should record when companies enter attractive valuation zones.

Example:

```text
EXLS

2026-08-20

Market Price:
$37

Intrinsic Value:
$44

MOS:
16%

Status:
ATTRACTIVE
```

Later:

```text
2026-10-15

Market Price:
$31

Intrinsic Value:
$45

MOS:
31%

Status:
MARGIN_OF_SAFETY
```

This allows future analysis of:

> How often do high-quality companies actually enter our preferred buying range?

That information can improve patience and capital allocation.

---

# 108. Missed Opportunity Review

ValuePilot should explicitly study missed opportunities.

Example:

```text
Company:
ABC

Research Date:
2026

Intrinsic Value:
$100

Market Price:
$65

Decision:
NO ACTION

Subsequent Price:
$160
```

The review should not conclude:

> We should have bought because the stock went up.

Instead ask:

```text
Was our thesis correct?

Was our valuation correct?

What prevented action?

Was uncertainty real?

Did we require excessive certainty?

Were we afraid of market conditions?

Did position-sizing rules prevent action?

Was the opportunity outside our circle of competence?
```

This is especially useful for improving investor behavior.

---

# 109. Circle of Competence

Every company should have:

```text
Understanding Confidence
```

Possible states:

```text
LOW

MEDIUM

HIGH
```

A company can have:

```text
High Financial Quality
```

but:

```text
Low Understanding Confidence
```

and therefore not qualify for investment.

ValuePilot should explicitly recognize:

> **We do not understand this business well enough.**

That is a valid investment conclusion.

---

# 110. Unknowns

The system should maintain:

```text
Known Facts

Known Unknowns

Potential Unknown Unknowns
```

Known unknowns should be explicit.

Example:

```text
EXLS

Known Unknown:
How much AI productivity benefit will ultimately be retained by EXLS?
```

Uncertainty should not be hidden inside a numerical score.

---

# 111. Confidence Is Not Probability of Stock Price Rising

Thesis confidence must mean:

> **Confidence that the underlying business hypothesis is correct.**

It must not mean:

> Probability that the stock goes up.

Example:

```text
Business Thesis Confidence:
85%

Current Valuation:
Very Expensive

Investment Opportunity:
Poor
```

This distinction is fundamental.

---

# 112. Price Should Not Contaminate Quality Analysis

Whenever possible, the system should first evaluate:

```text
Business Quality
```

without seeing the current market price.

Then evaluate valuation separately.

This reduces anchoring.

The preferred sequence is:

```text
Understand Business
      ↓
Assess Quality
      ↓
Estimate Economics
      ↓
Estimate Intrinsic Value
      ↓
Observe Market Price
      ↓
Evaluate Opportunity
```

rather than:

```text
Observe Cheap Stock
      ↓
Find Reasons to Like It
```

---

# 113. Bull / Bear Steelman

For every serious candidate, ValuePilot should generate:

```text
Strongest Bull Case
```

and:

```text
Strongest Bear Case
```

The objective is not artificial balance.

The objective is to identify:

> **The real disagreement between intelligent investors.**

Then identify:

```text
Key Variables That Determine Which Side Is Correct
```

For EXLS, one such variable might be:

> Whether its growth advantage over peers is structural or merely stage-of-scale related.

This should become a persistent research question.

---

# 114. Key Variable Framework

Every company should eventually have a small set of:

# Key Decision Variables

These are the variables that would most change intrinsic value or thesis confidence.

Example:

```text
EXLS

K1:
Long-term organic revenue growth

K2:
AI productivity economics

K3:
Revenue per employee

K4:
Customer wallet-share expansion

K5:
Incremental ROIC

K6:
Competitive intensity
```

ValuePilot should prioritize collecting evidence about these variables.

This prevents research from becoming unfocused.

The purpose is not to know everything about a company.

It is to know the variables that matter most.

---

# 115. Key Variable Monitoring

Each Key Decision Variable should maintain:

```text
Current State

Historical Trend

Expected Range

Thesis Sensitivity

Valuation Sensitivity

Confidence

Supporting Evidence

Contradicting Evidence

Last Updated
```

Example:

```text
Company:
EXLS

Key Variable:
Long-Term Organic Revenue Growth

Current Estimate:
10–12%

Previous Estimate:
9–11%

Direction:
Improving

Confidence:
Medium-High

Valuation Sensitivity:
Very High
```

If a variable has high valuation sensitivity, the system should assign it higher research priority.

---

# 116. Thesis Sensitivity Analysis

Not every assumption matters equally.

ValuePilot should identify which assumptions drive most of the valuation.

Example:

```text
EXLS Valuation Sensitivity

Revenue Growth:
VERY HIGH

Operating Margin:
HIGH

Terminal Growth:
MEDIUM

Discount Rate:
HIGH

SBC:
MEDIUM

Net Debt:
LOW
```

The system should focus research effort on:

> **High-impact + high-uncertainty variables**

rather than low-impact details.

---

# 117. Research Priority Matrix

A useful framework is:

```text
Research Priority
=
Impact on Decision
×
Uncertainty
×
Likelihood of New Evidence
```

Possible categories:

```text
CRITICAL

HIGH

MEDIUM

LOW
```

Example:

```text
EXLS

AI productivity economics:
CRITICAL

Long-term growth durability:
CRITICAL

Next-quarter EPS:
LOW

Daily stock-price movement:
LOW
```

This is how ValuePilot should allocate research attention.

---

# 118. Change Detection Before Explanation

Whenever new data arrives, the system should first identify:

> **What changed numerically?**

Only then should it explain why.

Correct workflow:

```text
New Data
   ↓
Detect Change
   ↓
Measure Magnitude
   ↓
Compare with History
   ↓
Compare with Expectations
   ↓
Interpret Cause
   ↓
Update Thesis
```

This reduces narrative-first reasoning.

---

# 119. Expectations vs. Actual Results

Every earnings update should compare:

```text
Previous Internal Expectation

Management Guidance

Reported Actual

Consensus Estimate
```

But consensus should remain secondary.

The most important comparison is:

> **What happened relative to our thesis?**

Example:

```text
EXLS

Our Organic Growth Expectation:
10–12%

Actual:
14%

Management Guidance:
Raised

Conclusion:
Evidence stronger than our base thesis.
```

This is more useful than merely reporting an earnings beat.

---

# 120. Guidance Tracking

Management guidance should be treated as evidence, but not as fact.

ValuePilot should maintain:

```text
Guidance Issued

Guidance Revised

Actual Result

Management Accuracy

Bias
```

Possible management patterns:

```text
CONSERVATIVE

RELIABLE

AGGRESSIVE

INCONSISTENT
```

This historical credibility should influence how much weight future guidance receives.

---

# 121. Management Language Delta

Earnings calls contain useful qualitative changes.

ValuePilot should compare management language across quarters.

Examples:

```text
Demand:
Strong → Stable

Pricing:
Stable → Increasing Pressure

AI Pipeline:
Early → Accelerating

Customer Budget:
Healthy → Cautious
```

The purpose is not sentiment analysis for its own sake.

It is to detect:

> **meaningful changes in management's description of business conditions.**

---

# 122. Management Q&A Extraction

Prepared remarks are often highly polished.

Analyst Q&A can reveal more useful information.

ValuePilot should extract questions related to:

```text
Growth Sustainability

Margins

Pricing

Customer Concentration

Competition

AI Economics

Capital Allocation

Guidance Assumptions

Demand Weakness

Execution Risks
```

The system should distinguish:

```text
Management Claim

Management Evidence

Management Avoidance
```

Repeatedly avoiding an important question can itself be useful evidence.

---

# 123. Claim Tracking

Important management claims should be stored as testable claims.

Example:

```text
Claim:
AI will improve employee productivity.

Date:
2026 Q2

Expected Evidence:
Revenue growth exceeds employee growth.

Review Horizon:
4–8 quarters
```

Later, ValuePilot can test whether the claim was actually supported.

This converts narrative into measurable evidence.

---

# 124. Leading vs. Lagging Indicators

ValuePilot should distinguish:

```text
Leading Indicators
```

from:

```text
Lagging Financial Results
```

For example, depending on the company:

```text
Bookings

Backlog

Customer Wins

Retention

Pricing

Utilization

Capacity Expansion

Order Growth

Pipeline

Traffic
```

may lead future revenue.

The system should identify the most relevant leading indicators for each business model.

---

# 125. Industry-Specific KPI Templates

Different businesses require different analytical templates.

Examples:

## SaaS

```text
ARR
NRR
CAC
LTV
Gross Margin
RPO
Churn
```

## Semiconductor

```text
ASP
Units
Inventory
Utilization
CapEx
Node Mix
Supply / Demand
```

## Insurance

```text
Combined Ratio
Premium Growth
Loss Ratio
Reserve Development
Investment Yield
```

## IT Services / BPO

```text
Organic Growth
Headcount
Revenue per Employee
Utilization
Bookings
Large Clients
Client Concentration
Offshore Mix
Margin
```

ValuePilot should not force every company into one generic schema.

---

# 126. Business Model Templates

Each major business model should eventually have a reusable analytical template.

Examples:

```text
Software

Payment Network

Marketplace

Bank

Insurance

Asset Manager

Semiconductor

Industrial

Retail

BPO / IT Services

Data Provider

Subscription Business

Commodity Producer
```

This improves consistency across company analysis.

---

# 127. Economic Driver Graph

For important companies, ValuePilot should maintain a causal model.

Example:

```text
Customer Growth
      ↓
Revenue

Wallet Share
      ↓
Revenue

Revenue per Employee
      ↓
Margin

Margin
      ↓
Owner Earnings

Owner Earnings
      ↓
Intrinsic Value
```

The purpose is to connect operational evidence to valuation.

---

# 128. Causal Reasoning

The system should avoid reasoning like:

```text
Revenue grew
therefore
moat improved
```

Instead:

```text
Revenue Growth
      ↓
Possible Causes

Industry Growth

Pricing

Market Share Gain

Acquisition

Temporary Demand

Competitive Advantage
```

ValuePilot should actively test alternative explanations.

---

# 129. Alternative Explanation Engine

For every material positive or negative development, ask:

> **What else could explain this?**

Example:

```text
Observation:
EXLS grows 14%.

Hypothesis A:
Superior competitive position.

Hypothesis B:
Smaller scale.

Hypothesis C:
Temporary industry demand.

Hypothesis D:
Acquisition contribution.

Hypothesis E:
Pricing.
```

The system should look for evidence that distinguishes between these hypotheses.

---

# 130. Comparative Base Rates

ValuePilot should use relevant base rates where useful.

Example:

> How often do IT services companies sustain >10% organic growth after reaching $5B revenue?

or:

> How often do high-growth SaaS companies maintain 30%+ growth after reaching $10B ARR?

Base rates should not override company-specific evidence.

But they should prevent unrealistic extrapolation.

---

# 131. Base Rate vs. Company-Specific Evidence

The system should combine:

```text
Base Rate

Company-Specific Evidence
```

A company should be allowed to outperform the base rate only when sufficient evidence exists.

Example:

```text
Industry Base Rate:
6–8% growth

EXLS Current Growth:
14%

Question:
What evidence justifies assuming sustained >10% growth?
```

This keeps valuation assumptions disciplined.

---

# 132. Scenario Analysis

Every material valuation should include:

```text
Bear Case

Base Case

Bull Case
```

Each scenario must have explicit assumptions.

Example:

```text
Bear:
Growth = 7%
Margins = Flat
Competitive Advantage Period = 5 years

Base:
Growth = 10%
Margins = Slightly Higher
CAP = 10 years

Bull:
Growth = 12%
Margins = Expanding
CAP = 15 years
```

Scenarios should reflect economic hypotheses, not arbitrary percentages.

---

# 133. Scenario Triggers

Each scenario should also define what evidence would make it more likely.

Example:

```text
Bull Case Trigger:

Revenue growth >12%

Revenue per employee improves

Large-client wallet share expands

Margins improve

Incremental ROIC remains high
```

Bear case trigger:

```text
Organic growth <7%

Customer losses

Margin compression

ROIC deterioration

Employee growth exceeds revenue growth
```

This connects scenario analysis directly to future evidence.

---

# 134. Valuation Delta Attribution

Whenever intrinsic value changes, ValuePilot should explain why.

Example:

```text
EXLS

Previous Value:
$44

New Value:
$48

Attribution:

Growth Assumption:
+$2.50

Margin Assumption:
+$1.20

Lower Share Count:
+$0.80

Higher Debt:
-$0.50
```

This prevents arbitrary target-price changes.

---

# 135. Thesis Delta Attribution

Similarly:

```text
Previous Thesis Confidence:
75%

New:
82%

Drivers:

Revenue Growth:
+3%

Customer Expansion:
+2%

Productivity Evidence:
+2%

SBC:
0%

Leverage:
0%
```

The exact numerical implementation can remain approximate.

But the reasoning should always be explicit.

---

# 136. Evidence Strength Framework

Evidence can be classified as:

```text
VERY_STRONG

STRONG

MODERATE

WEAK

ANECDOTAL
```

Possible hierarchy:

```text
Audited Financial Result
>
Repeated Operating Evidence
>
Customer / Industry Evidence
>
Management Statement
>
Analyst Opinion
>
Media Speculation
```

The exact hierarchy may vary by context.

---

# 137. Evidence Decay

Some evidence becomes stale.

For example:

```text
Customer relationship remains strong
```

from five years ago should carry less weight today.

ValuePilot should consider:

```text
Evidence Age

Evidence Persistence

Evidence Relevance
```

Structural evidence may decay slowly.

Temporary evidence should decay faster.

---

# 138. Structural vs. Cyclical Evidence

Every major development should be classified where possible as:

```text
STRUCTURAL

CYCLICAL

TEMPORARY

UNCERTAIN
```

Example:

```text
Industry recession:
CYCLICAL

Permanent loss of market share:
STRUCTURAL

One-time outage:
TEMPORARY
```

This classification should influence thesis updates.

---

# 139. Market Price Monitoring

Market price should be monitored separately from business evidence.

The system should detect when price moves materially without corresponding thesis change.

Example:

```text
Business Thesis:
Unchanged

Intrinsic Value:
Unchanged

Stock Price:
-25%
```

This may create:

```text
VALUATION_OPPORTUNITY
```

Price changes are important only because they may alter expected return.

---

# 140. Opportunity Trigger Engine

Possible triggers:

```text
Price <= Fair Value

Price <= MOS Price

Effective Put Cost <= Put Underwriting Price

Thesis Upgraded + Price Unchanged

Intrinsic Value Increased + Price Unchanged

Price Fell + Thesis Stable
```

These should move a company into a higher human-review priority.

---

# 141. Avoid Price Anchoring

ValuePilot should avoid using prior market highs as a valuation anchor.

Bad reasoning:

```text
Stock used to trade at $80.
Now it is $40.
Therefore it is cheap.
```

Correct reasoning:

```text
Intrinsic Value:
$45

Current Price:
$40

Therefore:
Slightly undervalued.
```

Historical price is not intrinsic value.

---

# 142. Avoid Multiple Anchoring

Similarly:

```text
Historical P/E:
30x

Current P/E:
20x
```

does not automatically mean cheap.

The system should ask:

> Has growth, moat, or capital return changed?

Multiples should be used as sanity checks, not as the primary definition of value.

---

# 143. Reverse DCF as a Required Check

For high-growth companies, reverse DCF should become a standard review.

Ask:

> What growth and margin assumptions does the current stock price imply?

Then compare:

```text
Market-Implied Expectations
```

with:

```text
ValuePilot Thesis Expectations
```

Large favorable gaps may indicate opportunity.

Large unfavorable gaps may indicate risk.

---

# 144. Expected Return Framework

ValuePilot should eventually estimate expected return from:

```text
Owner Earnings Growth

Dividend Yield

Net Buyback Yield

Valuation Change
```

Conceptually:

```text
Expected Return
≈
Owner Earnings Growth
+
Shareholder Yield
+
Change in Valuation
```

This helps compare different opportunities.

---

# 145. Quality of Expected Return

Two investments with the same expected return may have very different quality.

Example:

```text
Company A:
12% expected return
High confidence

Company B:
12% expected return
Low confidence
```

ValuePilot should distinguish:

```text
Expected Return
```

from:

```text
Confidence-Adjusted Expected Return
```

without pretending to precise mathematical certainty.

---

# 146. Downside Analysis

Every investment candidate should include:

```text
Permanent Capital Loss Risk

Temporary Drawdown Risk

Business Deterioration Risk

Balance Sheet Risk

Valuation Compression Risk
```

The main Buffett/Munger concern is:

> **Permanent loss of capital**

not normal price volatility.

---

# 147. Stress Testing

For important positions, ValuePilot should stress:

```text
Revenue -10%

Margins -300 bps

Growth permanently slower

Higher interest rates

Customer loss

Recession

Multiple compression
```

Then estimate:

```text
Bear Intrinsic Value

Balance Sheet Resilience

Likely Recovery Path
```

---

# 148. Kill Criteria

Every serious investment thesis should have explicit:

# Kill Criteria

Examples:

```text
Moat permanently impaired

Accounting credibility lost

Management integrity issue

Balance sheet becomes dangerous

Capital allocation becomes persistently destructive

Core growth thesis falsified
```

When triggered, the system should not simply reduce a score.

It should generate:

```text
THESIS_BROKEN
```

and require immediate human review.

---

# 149. Watch Conditions

Not every concern is a kill criterion.

Possible state:

```text
WATCH
```

Example:

```text
SBC rising

Leverage rising

Customer concentration increasing

Growth decelerating
```

ValuePilot should distinguish:

```text
Watch

Concern

Thesis Conflict

Thesis Broken
```

---

# 150. Research State Machine

A company may move through:

```text
DISCOVERED
    ↓
INITIAL_RESEARCH
    ↓
THESIS_FORMED
    ↓
QUALIFIED
    ↓
WAIT_FOR_PRICE
    ↓
ATTRACTIVE
    ↓
MOS
    ↓
PUT_CANDIDATE
    ↓
OWNED
```

Possible negative branches:

```text
THESIS_CONFLICT

REJECTED

THESIS_BROKEN

EXIT_REVIEW
```

This provides a clear research workflow.

---

# 151. Human Review Queue

The Human Review Queue should prioritize:

```text
1. Thesis Broken

2. Falsification Alerts

3. Major Thesis Downgrades

4. Exceptional Valuation Opportunities

5. Put Underwriting Candidates

6. Major Thesis Upgrades

7. New High-Quality Candidates

8. Open Research Questions
```

This keeps human attention focused on the most decision-relevant items.

---

# 152. Human Override

Human decisions should be able to override AI classifications.

However, the system should record:

```text
AI Recommendation

Human Decision

Reason for Override
```

This allows future postmortem analysis.

---

# 153. No Hidden AI State

Important investment conclusions must not exist only inside model context.

They should be persisted explicitly.

For example:

```text
Thesis

Evidence

Confidence

Valuation Assumptions

Open Questions

Decision
```

must live in durable storage.

LLM context is temporary.

Investment memory must be persistent.

---

# 154. Reproducible Analysis

Where practical, financial calculations should be performed by deterministic code rather than LLM reasoning.

Examples:

```text
FCF

ROIC

Share Count Change

Revenue CAGR

Margin Trends

DCF

Reverse DCF

Option Effective Cost
```

LLMs should focus on:

```text
Interpretation

Hypothesis Formation

Evidence Mapping

Contradictory Evidence

Qualitative Analysis
```

This separation improves reliability.

---

# 155. LLM + Deterministic Engine

Ideal architecture:

```text
Deterministic Financial Engine
        +
LLM Research Engine
        +
Persistent Thesis Database
        +
Human Judgment
```

Each component does what it is best at.

---

# 156. Source Citation Requirement

Every material fact used in a thesis update should preserve:

```text
Source Type

Source URL / Identifier

Document Date

Published Date

Relevant Section

Extraction Timestamp
```

For SEC documents, preserve:

```text
CIK

Accession Number

Filing Type

Reporting Period
```

This enables auditability.

---

# 157. Data Confidence

Facts should have data-confidence states such as:

```text
VERIFIED_PRIMARY_SOURCE

VERIFIED_SECONDARY_SOURCE

MANAGEMENT_CLAIM

ESTIMATED

INFERRED

UNVERIFIED
```

The thesis engine should weigh evidence accordingly.

---

# 158. Missing Data

ValuePilot should explicitly represent missing data.

Do not silently substitute guesses.

Example:

```text
Revenue per Employee:
UNKNOWN
```

is better than:

```text
Revenue per Employee:
Estimated with low confidence
```

unless the estimate is explicitly labeled.

---

# 159. Uncertainty as First-Class Data

Important fields should allow:

```text
Value

Range

Confidence

Source

Assumptions
```

Example:

```text
Long-Term Organic Growth

Base:
10%

Range:
7–12%

Confidence:
Medium
```

This avoids false precision.

---

# 160. Investment Memo Generation

ValuePilot should eventually generate a concise human-readable investment memo from structured thesis data.

The memo should include:

```text
Business

Why It Is Good

Moat

Growth

Capital Allocation

Key Risks

Bear Case

Bull Case

Key Variables

Valuation

MOS Price

Open Questions

Thesis Changes

Human Decision
```

The memo should be generated from the database.

It should not become the database itself.

---

# 161. One-Page Decision View

For daily use, the ideal final output should be compact.

Example:

```text
EXLS

QUALITY
8.1 / 10

THESIS
Stable / Improving

FAIR VALUE
$44

MOS
$33

PRICE
$31.80

KEY CHANGE
Organic growth remained >12%.

MAIN RISK
AI productivity economics remain unconfirmed.

STATUS
MARGIN_OF_SAFETY

ACTION
HUMAN REVIEW
```

The system should hide complexity until deeper inspection is needed.

---

# 162. Research Drill-Down

From the one-page view, the investor should be able to drill into:

```text
Financial History

Thesis History

Evidence

Competitive Analysis

Valuation Assumptions

Management

Open Questions

Option Opportunities

Decision History
```

This provides both simplicity and depth.

---

# 163. Searchable Investment Memory

The user should eventually be able to ask:

```text
Show me all companies where moat confidence increased
during the last four quarters.
```

or:

```text
Which high-quality companies are now trading
more than 25% below intrinsic value?
```

or:

```text
Which investment theses have unresolved
customer-concentration risks?
```

or:

```text
Which companies did we reject because
we thought growth was unsustainable?
```

The thesis database should make these queries possible.

---

# 164. Research Comparison Queries

The system should support questions such as:

```text
Compare EXLS and Genpact
using only evidence available as of 2026-08-20.
```

or:

```text
Which company has the better incremental ROIC?
```

or:

```text
Why is EXLS growing faster than Genpact?
```

The answers should draw from persistent evidence, not fresh ad hoc narratives.

---

# 165. Investment Universe Management

ValuePilot should maintain multiple universes.

Examples:

```text
AI Companies

High-Growth Quality Companies

Core Quality Companies

Current Holdings

Put Underwriting Universe

Watchlist

Rejected Companies
```

A company may belong to multiple universes.

---

# 166. Universe-Specific Rules

Different universes may use different screening rules.

Example:

```text
High-Growth Quality Universe

Projected Sales Growth >=10%

ROE >=15%

Financial Strength >=B+

Market Cap >=$2B
```

But after initial screening, every company should enter the same deeper thesis framework.

Quantitative screens should find candidates.

They should not make investment decisions.

---

# 167. Screening vs. Research

The architecture should clearly separate:

```text
SCREENING
```

from:

```text
RESEARCH
```

Screening asks:

> Which companies deserve attention?

Research asks:

> Which businesses deserve capital?

This distinction should remain explicit throughout ValuePilot.

---

# 168. Daily Opportunity Scan

Once the thesis database is sufficiently populated, daily scanning becomes powerful.

The system can ask:

```text
Which high-quality companies became cheaper today?

Which companies entered MOS?

Which thesis improved recently while price fell?

Which Put contracts now create attractive assignment prices?
```

This is much more valuable than scanning the entire market blindly every day.

---

# 169. Opportunity Exists in the Intersection

The ideal investment target sits at the intersection of:

```text
High Quality

Durable Growth

High Thesis Confidence

Reasonable Valuation

Large Margin of Safety

Attractive Optionality
```

Very few companies will satisfy all conditions simultaneously.

That is desirable.

ValuePilot should help the investor wait.

---

# 170. Patience as a System Feature

A disciplined investment system should make:

```text
DO NOTHING
```

a valid output.

Example:

```text
Excellent Company

Strong Thesis

Price Too High

Action:
WAIT
```

The system should not feel compelled to generate trades.

---

# 171. Opportunity Cost

Every investment candidate should eventually be compared against alternatives.

The question is not:

> Is EXLS attractive?

It is:

> Is EXLS more attractive than the other opportunities available for the same capital?

ValuePilot should support ranked opportunity comparisons.

---

# 172. Capital Allocation Queue

Potential investments can enter a queue:

```text
Company

Expected Return

Quality

Thesis Confidence

MOS

Risk

Portfolio Fit
```

The human investor decides where capital goes.

This extends Buffett/Munger thinking from company analysis to portfolio capital allocation.

---

# 173. Put Opportunity Queue

Similarly:

```text
Ticker

Strike

DTE

Premium

Effective Cost

Intrinsic Value

MOS

Thesis Confidence

Liquidity

Annualized Yield
```

Then rank candidates based on underwriting quality.

The highest premium should not necessarily rank first.

---

# 174. Portfolio Risk Engine Integration

Option underwriting should consider:

```text
Single-Name Exposure

Sector Exposure

Factor Exposure

Macro Correlation

Assignment Exposure

Total Cash Required

Worst-Case Simultaneous Assignment
```

Fundamental attractiveness does not eliminate portfolio risk.

---

# 175. Decision Support, Not Decision Replacement

The system may output:

```text
Recommended for Review
```

but it should never imply:

```text
You should definitely buy.
```

The final decision requires human judgment.

This principle should remain explicit in both architecture and UI.

---

# 176. Core Architecture Summary

The entire system can be summarized as:

```text
                DATA
                 ↓
               FACTS
                 ↓
              EVIDENCE
                 ↓
             HYPOTHESES
                 ↓
               THESIS
                 ↓
            THESIS DELTA
                 ↓
             VALUATION
                 ↓
            OPPORTUNITY
                 ↓
          OPTION ANALYSIS
                 ↓
           HUMAN REVIEW
                 ↓
          HUMAN DECISION
                 ↓
              OUTCOME
                 ↓
            POSTMORTEM
                 ↓
              LEARNING
                 ↓
         BETTER FUTURE THESIS
```

---

# 177. Recommended Implementation Priority

The most important implementation sequence is:

## Priority 1 — Company Thesis State

Build:

```text
CompanyThesisState

InvestmentHypothesis

RiskHypothesis

FalsificationCondition

ThesisEvidence

ThesisDelta
```

before scaling ingestion.

---

## Priority 2 — Financial State

Build:

```text
Quarterly Financial History

Owner Earnings

ROIC

Incremental ROIC

SBC

Share Count

Capital Allocation
```

---

## Priority 3 — Valuation State

Build:

```text
Bear

Base

Bull

MOS Price

Put Underwriting Price

Reverse DCF
```

---

## Priority 4 — SEC / Earnings Automation

Then automate:

```text
SEC Detection

Fact Extraction

Earnings Release

Investor Presentation

Earnings Call

Management Q&A

Guidance
```

---

## Priority 5 — Thesis Delta

Every new information item should answer:

> **What changed?**

---

## Priority 6 — News Evidence Engine

Only ingest news that may affect:

```text
Moat

Growth

Management

Capital Allocation

Risk

Valuation
```

---

## Priority 7 — Weekly Review

Build the human review workflow.

---

## Priority 8 — Opportunity Engine

Identify attractive companies and MOS situations.

---

## Priority 9 — Option Engine Integration

Use fundamental underwriting price before analyzing premium.

---

## Priority 10 — Decision Journal

Build the long-term learning loop.

---

# 178. Initial MVP

The first practical MVP does not need the entire architecture.

A useful MVP should contain:

```text
1. CompanyThesisState

2. 5–10 explicit hypotheses per company

3. Supporting / contradicting evidence

4. Falsification conditions

5. Eight-quarter financial history

6. Buffett / Munger quality analysis

7. Bear / Base / Bull valuation

8. Thesis Delta after new earnings

9. Human Review Queue

10. Persistent history
```

This alone would already create substantial value.

---

# 179. MVP Test Company

EXLS is a good first end-to-end test case.

Reasons:

```text
Understandable Business

Strong Growth

Meaningful Competition

AI Thesis

Measurable Financial History

Capital Allocation Questions

Valuation Questions

Option Potential
```

We can use EXLS to validate the entire workflow:

```text
Raw Filing
   ↓
Facts
   ↓
Thesis
   ↓
Evidence
   ↓
Thesis Delta
   ↓
Valuation
   ↓
Opportunity
   ↓
Put Underwriting
   ↓
Human Review
```

If the architecture works well for EXLS, it can then be generalized.

---

# 180. Definition of Success for the MVP

The EXLS MVP should be able to answer:

```text
What do we currently believe about EXLS?

Why?

What evidence supports that belief?

What evidence contradicts it?

What has changed since last quarter?

What are the most important unresolved questions?

What would prove us wrong?

What is the current intrinsic value range?

At what price would we want to own the company?

At what effective Put assignment price would underwriting be attractive?
```

If ValuePilot can answer these reliably from persistent state, the architecture is working.

---

# 181. Longer-Term Goal

Over time, ValuePilot should become capable of maintaining hundreds of company theses.

However, the system should not attempt deep research on hundreds of companies simultaneously.

Companies should receive different research depth based on:

```text
Quality

Opportunity

Portfolio Relevance

Thesis Change

Research Priority
```

This creates scalable research coverage.

---

# 182. Institutional Memory

The ultimate benefit of the system is:

> **The investment process no longer resets every time we reopen a company.**

Instead:

```text
Research compounds.

Evidence compounds.

Understanding compounds.

Judgment improves.

Mistakes become reusable lessons.
```

This is the core strategic advantage of ValuePilot.

---

# 183. Final Product Philosophy

ValuePilot should not try to predict every stock move.

It should help answer a smaller number of much more important questions:

```text
Is this a good business?

Why?

Is the moat durable?

Can it reinvest at high returns?

Is management rational?

What could prove us wrong?

What is the business worth?

How uncertain is that estimate?

What does the market already expect?

Is there a meaningful Margin of Safety?

Would we be happy to own it if assigned through a Put?

What changed since the last time we looked?
```

If ValuePilot answers these questions consistently, it will become much more useful than a conventional screener.

---

# 184. Final Guiding Principles

ValuePilot should follow these principles:

1. **Facts before opinions.**
2. **Primary sources before secondary sources.**
3. **Persistent thesis before fresh narrative.**
4. **Evidence before confidence changes.**
5. **Contradictory evidence must be actively sought.**
6. **Business quality and valuation must remain separate.**
7. **Intrinsic value is a range, not a precise point.**
8. **Owner Earnings matter more than adjusted storytelling.**
9. **Incremental ROIC matters more than historical ROIC alone.**
10. **Growth quality matters more than growth rate alone.**
11. **A moat must be testable.**
12. **Every major thesis needs falsification conditions.**
13. **Price changes do not equal thesis changes.**
14. **News matters only when it changes evidence.**
15. **Option premium is downstream of fundamental underwriting.**
16. **A high premium does not make a bad business attractive.**
17. **Do nothing is a valid investment decision.**
18. **Historical decisions must be reviewed without hindsight bias.**
19. **AI maintains memory and discipline; humans allocate capital.**
20. **The objective is better decisions, not more decisions.**

---

# 185. Final Principle

The central rule for ValuePilot is:

> **Do not automate opinions. Automate evidence collection, memory, comparison, contradiction detection, and disciplined thesis updating.**

AI should help the investor:

```text
Remember Better

See Changes Earlier

Challenge Beliefs

Compare Businesses

Estimate Value

Recognize Opportunity

Avoid Repeating Mistakes
```

But:

# The final investment judgment remains human.

ValuePilot should therefore become:

> **A persistent investment intelligence and decision-support system that compounds knowledge over time.**

---

**End of Document**