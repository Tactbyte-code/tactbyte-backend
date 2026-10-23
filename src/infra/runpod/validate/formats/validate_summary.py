# ----------- Summary-sample ------------
# {
#   "schema_version": "1.0",
#   "report_id": "rpt_7c1d9e42",
#   "query_id": "q_8f3a2c1e",
#   "status": "COMPLETED",
#   "generated_at": "2026-10-15T09:30:00Z",
#   "idea": {
#     "title": "Automated invoice chasing for freelancers",
#     "description": "A tool that tracks client invoices and sends polite automated payment reminders.",
#     "industry": "Fintech / SaaS",
#     "stage": "idea",
#     "location": "Guwahati",
#     "country_iso2": "IN",
#     "business_type": "digital",
#     "target_segment": "freelancers and solo consultants who invoice clients",
#     "problem_statement": "Freelancers lose time and cash flow chasing late client payments."
#   },
#   "overall": {
#     "viability_score": 61.7,
#     "scale": "0-100, higher is more favourable for launching",
#     "band": "Promising",
#     "band_scale": [
#       { "min": 75, "label": "Strong" },
#       { "min": 55, "label": "Promising" },
#       { "min": 40, "label": "Mixed" },
#       { "min": 0, "label": "Weak" }
#     ],
#     "confidence": "medium",
#     "verdict": "The pain is real and recurring, and launch costs are modest, but the invoicing space is crowded and several figures rest on assumptions.",
#     "score_breakdown": [
#       { "parameter": "pain", "label": "Problem and pain-point severity", "weight": 0.20, "effective_weight": 0.2105, "score": 69.0, "rating": "moderate", "confidence": "high", "status": "scored", "contribution": 14.5 },
#       { "parameter": "market", "label": "Market size and growth", "weight": 0.15, "effective_weight": 0.1579, "score": 64.0, "rating": "moderate", "confidence": "low", "status": "scored", "contribution": 10.1 },
#       { "parameter": "competition", "label": "Competition and differentiation", "weight": 0.15, "effective_weight": 0.1579, "score": 48.0, "rating": "weak", "confidence": "medium", "status": "scored", "contribution": 7.6 },
#       { "parameter": "demand", "label": "Demand signals", "weight": 0.10, "effective_weight": 0.1053, "score": 58.0, "rating": "moderate", "confidence": "medium", "status": "scored", "contribution": 6.1 },
#       { "parameter": "unit_economics", "label": "Unit economics and pricing", "weight": 0.10, "effective_weight": 0.1053, "score": 55.0, "rating": "moderate", "confidence": "low", "status": "scored", "contribution": 5.8 },
#       { "parameter": "cost", "label": "Startup cost and runway", "weight": 0.10, "effective_weight": 0.1053, "score": 70.0, "rating": "strong", "confidence": "medium", "status": "scored", "contribution": 7.4 },
#       { "parameter": "regulatory", "label": "Feasibility and regulatory risk", "weight": 0.10, "effective_weight": 0.1053, "score": 66.0, "rating": "moderate", "confidence": "low", "status": "scored", "contribution": 6.9 },
#       { "parameter": "survival_funding", "label": "Funding climate and survival", "weight": 0.05, "effective_weight": 0.0, "score": null, "rating": null, "confidence": null, "status": "insufficient_data", "contribution": null },
#       { "parameter": "macro", "label": "Macro and timing", "weight": 0.05, "effective_weight": 0.0526, "score": 62.0, "rating": "moderate", "confidence": "medium", "status": "scored", "contribution": 3.3 }
#     ],
#     "strengths": [
#       "Recurring, first-hand complaints about late payments across several independent sources",
#       "Low estimated launch cost for a digital product",
#       "Rising discussion volume around late payments"
#     ],
#     "risks": [
#       "Crowded market with several established invoicing tools",
#       "Willingness to pay is only weakly evidenced",
#       "CAC and churn are assumptions, not measured data",
#       "No funding or survival data available for this sector and country"
#     ]
#   },
#   "parameters": {
#     "pain": {
#       "score": 69.0,
#       "band": "Significant",
#       "confidence": "high",
#       "effective_sample": 27.8,
#       "components": { "volume": 0.78, "intensity": 0.71, "breadth": 0.66, "payment": 0.36, "gap": 0.86 },
#       "counts": {
#         "collected": 412,
#         "after_dedupe": 356,
#         "after_filter": 150,
#         "relevant": 63,
#         "by_source": { "hackernews": 140, "stackexchange": 88, "youtube": 60, "appstore": 112, "grounded_search": 12 }
#       },
#       "themes": [
#         { "label": "Chasing late client payments takes hours each month", "post_count": 22, "avg_intensity": 3.9, "example_urls": ["https://news.ycombinator.com/item?id=EXAMPLE_1"] },
#         { "label": "No reliable way to track which invoices are overdue", "post_count": 15, "avg_intensity": 3.4, "example_urls": ["https://news.ycombinator.com/item?id=EXAMPLE_2"] },
#         { "label": "Reminding clients feels awkward and risks the relationship", "post_count": 11, "avg_intensity": 3.2, "example_urls": ["https://stackexchange.com/questions/EXAMPLE_3"] },
#         { "label": "Existing tools charge too much for basic reminders", "post_count": 8, "avg_intensity": 2.8, "example_urls": ["https://apps.apple.com/app/EXAMPLE_4"] },
#         { "label": "GST invoice formats confuse freelancers", "post_count": 7, "avg_intensity": 3.0, "example_urls": ["https://stackexchange.com/questions/EXAMPLE_5"] }
#       ],
#       "top_evidence": [
#         { "source": "hackernews", "url": "https://news.ycombinator.com/item?id=EXAMPLE_1", "excerpt": "Clients pay weeks late and I spend Fridays writing reminder emails.", "intensity": 4, "workaround": "inadequate", "payment_signal": "implied" },
#         { "source": "appstore", "url": "https://apps.apple.com/app/EXAMPLE_4", "excerpt": "Reminders are locked behind the expensive plan, not worth it.", "intensity": 3, "workaround": "inadequate", "payment_signal": "explicit" }
#       ],
#       "caveats": [
#         "Online communities over-represent technical and English-speaking users.",
#         "Most sources cannot be filtered by country, so evidence may not reflect India."
#       ]
#     },
#     "market": {
#       "score": 64.0,
#       "confidence": "low",
#       "components": { "size_adequacy": 0.70, "growth": 0.62, "data_agreement": 0.55 },
#       "tam": {
#         "value": 54000000000, "currency": "INR", "label": "estimated", "method": "bottom_up",
#         "formula": "addressable_users x annual_price_per_user",
#         "inputs": [
#           { "name": "addressable_users", "value": 15000000, "unit": "people", "label": "estimated", "source_ids": ["src_wb_1"], "assumption_id": "as_01" },
#           { "name": "annual_price_per_user", "value": 3600, "unit": "INR/year", "label": "assumed", "assumption_id": "as_04" }
#         ],
#         "range": { "low": 36000000000, "base": 54000000000, "high": 72000000000 }
#       },
#       "sam": {
#         "value": 16200000000, "currency": "INR", "label": "estimated", "method": "bottom_up",
#         "formula": "TAM users x online_invoicing_share x annual_price_per_user",
#         "inputs": [
#           { "name": "online_invoicing_share", "value": 0.30, "unit": "ratio", "label": "assumed", "assumption_id": "as_02" }
#         ],
#         "serviceable_users": 4500000,
#         "range": { "low": 10800000000, "base": 16200000000, "high": 21600000000 }
#       },
#       "som": {
#         "value": 162000000, "currency": "INR", "label": "assumed", "method": "share_of_sam", "horizon_years": 3,
#         "formula": "SAM x obtainable_share",
#         "inputs": [
#           { "name": "obtainable_share", "value": 0.01, "unit": "ratio", "label": "assumed", "assumption_id": "as_03" }
#         ],
#         "obtainable_users": 45000,
#         "range": { "low": 81000000, "base": 162000000, "high": 324000000 }
#       },
#       "cross_check": { "method": "top_down", "value": 41000000000, "currency": "INR", "label": "estimated", "divergence_pct": -24.1, "note": "Top-down estimate is lower than bottom-up; treat TAM as a range." },
#       "growth": { "cagr_pct": 12.0, "horizon": "2026-2031", "label": "estimated", "confidence": "low", "basis": "Trend in self-employment counts and digital payment adoption", "source_ids": ["src_wb_1"] }
#     },
#     "demand": {
#       "score": 58.0,
#       "confidence": "medium",
#       "search_interest": { "available": false, "reason": "No official free API; unofficial Google Trends access is disabled." },
#       "signals": [
#         { "name": "Wikipedia pageviews: Invoice (index, 2025-Q4 = 100)", "source_ids": ["src_wiki"], "direction": "rising", "change_pct": 12.0,
#           "series": [ { "period": "2025-Q4", "value": 100 }, { "period": "2026-Q1", "value": 104 }, { "period": "2026-Q2", "value": 109 }, { "period": "2026-Q3", "value": 112 } ] },
#         { "name": "Discussion mentions: late payments and freelancers", "source_ids": ["src_hn", "src_se"], "direction": "rising", "change_pct": 50.0,
#           "series": [ { "period": "2025-Q4", "value": 14 }, { "period": "2026-Q1", "value": 17 }, { "period": "2026-Q2", "value": 16 }, { "period": "2026-Q3", "value": 21 } ] }
#       ]
#     },
#     "competition": {
#       "score": 48.0,
#       "confidence": "medium",
#       "saturation": "high",
#       "incumbent_strength": "moderate",
#       "counts": { "direct": 5, "indirect": 4 },
#       "direct_competitors": [
#         { "name": "Sample Competitor A", "url": "https://example.com/a", "offering": "Invoicing with automated payment reminders", "pricing_model": "subscription",
#           "price_from": { "amount": 299, "currency": "INR", "period": "month" }, "target_segment": "freelancers and small agencies",
#           "strengths": ["Automated reminders"], "weaknesses": ["Reminder wording is not customisable"],
#           "evidence_url": "https://example.com/a/pricing", "retrieved_at": "2026-10-15", "source_ids": ["src_vertex"], "confidence": "medium", "funding": null, "revenue": null },
#         { "name": "Sample Competitor B", "url": "https://example.com/b", "offering": "Free invoice generator with paid reminders", "pricing_model": "freemium",
#           "price_from": { "amount": 0, "currency": "INR", "period": "month" }, "target_segment": "individual freelancers",
#           "strengths": ["Free tier"], "weaknesses": ["Reminders only on the highest plan"],
#           "evidence_url": "https://example.com/b/pricing", "retrieved_at": "2026-10-15", "source_ids": ["src_vertex"], "confidence": "medium", "funding": null, "revenue": null },
#         { "name": "Sample Competitor C", "url": "https://example.com/c", "offering": "Pay-per-invoice billing platform", "pricing_model": "per_invoice",
#           "price_from": null, "target_segment": "small businesses",
#           "strengths": ["Payment collection built in"], "weaknesses": ["Fees on every invoice"],
#           "evidence_url": "https://example.com/c/pricing", "retrieved_at": "2026-10-15", "source_ids": ["src_vertex"], "confidence": "low", "funding": null, "revenue": null }
#       ],
#       "indirect_alternatives": ["Spreadsheets and manual email reminders", "Full accounting suites", "Messaging-app templates"],
#       "differentiation_gaps": [
#         "Relationship-friendly reminder tone and templates",
#         "Reminders included in a low-cost plan",
#         "Simple GST-ready invoice formats"
#       ],
#       "physical_density": null,
#       "caveats": ["Competitor revenue, traffic and funding are not available from free sources."]
#     },
#     "unit_economics": {
#       "score": 55.0,
#       "confidence": "low",
#       "pricing_benchmarks": {
#         "sample_size": 8,
#         "models": { "freemium": 3, "subscription": 4, "per_invoice": 1 },
#         "monthly_price": { "min": 0, "median": 299, "max": 999, "currency": "INR" },
#         "label": "sourced", "source_ids": ["src_vertex"]
#       },
#       "model": {
#         "arpu_monthly": 300, "gross_margin_pct": 80, "monthly_churn_pct": 4, "cac": 1200, "currency": "INR",
#         "label": "assumed", "assumption_ids": ["as_04", "as_05", "as_06", "as_07"]
#       },
#       "derived": { "ltv": 6000, "ltv_cac_ratio": 5.0, "cac_payback_months": 5.0, "break_even_paying_users": 625, "currency": "INR" },
#       "caveats": ["No reliable free CAC or churn data exists; these values are editable assumptions."]
#     },
#     "cost": {
#       "score": 70.0,
#       "confidence": "medium",
#       "currency": "INR",
#       "one_time": [
#         { "item": "Company registration", "low": 8000, "base": 15000, "high": 25000, "label": "estimated", "source_ids": ["src_gov_1"] },
#         { "item": "Legal and compliance setup", "low": 10000, "base": 20000, "high": 40000, "label": "estimated", "source_ids": ["src_gov_1"] },
#         { "item": "Brand and web presence", "low": 5000, "base": 15000, "high": 40000, "label": "assumed", "source_ids": [] },
#         { "item": "MVP build (2 developers, 3 months)", "low": 360000, "base": 540000, "high": 780000, "label": "estimated", "source_ids": ["src_ilo"], "assumption_id": "as_08" }
#       ],
#       "monthly": [
#         { "item": "Team salaries (2 developers)", "low": 90000, "base": 110000, "high": 160000, "label": "estimated", "source_ids": ["src_ilo"] },
#         { "item": "Cloud hosting and LLM/API usage", "low": 8000, "base": 15000, "high": 35000, "label": "estimated", "source_ids": ["src_vertex"] },
#         { "item": "Marketing (content and community)", "low": 10000, "base": 20000, "high": 50000, "label": "assumed", "source_ids": [] },
#         { "item": "Tools, payment-gateway fees, accounting", "low": 3000, "base": 5000, "high": 10000, "label": "assumed", "source_ids": [] }
#       ],
#       "totals": {
#         "one_time": { "low": 383000, "base": 590000, "high": 885000 },
#         "monthly_burn": { "low": 111000, "base": 150000, "high": 255000 },
#         "first_12_months": { "low": 1715000, "base": 2390000, "high": 3945000 }
#       },
#       "runway_months": null,
#       "runway_note": "Not calculated because no starting budget was provided."
#     },
#     "regulatory": {
#       "score": 66.0,
#       "confidence": "low",
#       "complexity": "low_to_medium",
#       "requirements": [
#         { "item": "Business registration", "applies": true, "note": "See cost.one_time for the estimate." },
#         { "item": "GST registration", "applies": "conditional", "note": "Depends on turnover thresholds and service type." },
#         { "item": "Personal data protection obligations for client contact details", "applies": true, "note": "Review the applicable data-protection law." },
#         { "item": "Payment licences", "applies": false, "note": "Not needed while reminders only link to third-party gateways." }
#       ],
#       "legal_review_recommended": true,
#       "source_ids": ["src_gov_1"]
#     },
#     "survival_funding": {
#       "status": "insufficient_data",
#       "score": null,
#       "reason": "No free source provides sector-level survival or seed-funding data for this country.",
#       "reference_benchmarks": [
#         { "region": "US", "metric": "5-year establishment survival", "value_pct": 50, "label": "sourced", "reference_only": true, "source_ids": ["src_bls"] }
#       ],
#       "funding_activity": null
#     },
#     "macro": {
#       "score": 62.0,
#       "confidence": "medium",
#       "outlook": "neutral_to_positive",
#       "indicators": [
#         { "name": "GDP growth (annual %)", "indicator_code": "NY.GDP.MKTP.KD.ZG", "value": 6.5, "year": 2024, "label": "sourced", "source_ids": ["src_wb_2"] },
#         { "name": "Inflation, consumer prices (annual %)", "indicator_code": "FP.CPI.TOTL.ZG", "value": 4.8, "year": 2024, "label": "sourced", "source_ids": ["src_wb_3"] },
#         { "name": "Self-employed (% of total employment)", "indicator_code": "SL.EMP.SELF.ZS", "value": 52.0, "year": 2024, "label": "sourced", "source_ids": ["src_wb_1"] }
#       ],
#       "timing_notes": ["Growth in self-employment supports the target segment.", "Inflation raises cost pressure on freelancers' tool budgets."]
#     }
#   },
#   "assumptions": [
#     { "id": "as_01", "name": "Addressable freelancers who invoice clients", "value": 15000000, "unit": "people", "label": "estimated", "affects": ["market"], "editable": true },
#     { "id": "as_02", "name": "Share who invoice online", "value": 0.30, "unit": "ratio", "label": "assumed", "affects": ["market"], "editable": true },
#     { "id": "as_03", "name": "Obtainable share of SAM by year 3", "value": 0.01, "unit": "ratio", "label": "assumed", "affects": ["market"], "editable": true },
#     { "id": "as_04", "name": "Average revenue per user per month", "value": 300, "unit": "INR", "label": "assumed", "affects": ["market", "unit_economics"], "editable": true },
#     { "id": "as_05", "name": "Gross margin", "value": 80, "unit": "percent", "label": "assumed", "affects": ["unit_economics"], "editable": true },
#     { "id": "as_06", "name": "Monthly churn", "value": 4, "unit": "percent", "label": "assumed", "affects": ["unit_economics"], "editable": true },
#     { "id": "as_07", "name": "Customer acquisition cost", "value": 1200, "unit": "INR", "label": "assumed", "affects": ["unit_economics"], "editable": true },
#     { "id": "as_08", "name": "MVP team and duration", "value": "2 developers x 3 months", "unit": null, "label": "assumed", "affects": ["cost"], "editable": true }
#   ],
#   "narrative": {
#     "executive_summary": "Freelancers repeatedly report time lost chasing late payments, and the cost to build a first version is modest. The invoicing space is crowded, however, and willingness to pay is only weakly evidenced, so the idea is promising rather than proven. Market size, churn and acquisition cost rest on editable assumptions.",
#     "citations": ["src_hn", "src_se", "src_as", "src_vertex", "src_wb_1"],
#     "sections": {
#       "pain": { "summary": "Late-payment chasing is a recurring, moderately intense problem; five themes cover all relevant posts.", "source_ids": ["src_hn", "src_se", "src_yt", "src_as"] },
#       "market": { "summary": "The estimated TAM is about INR 54 billion with a SOM of about INR 162 million by year 3, shown as ranges because the inputs are low-confidence.", "source_ids": ["src_wb_1"] },
#       "competition": { "summary": "Five direct competitors were found. Gaps exist in reminder tone and affordable reminder plans.", "source_ids": ["src_vertex"] },
#       "cost": { "summary": "First-year cost is estimated at INR 2.4 million (range 1.7 to 3.9 million).", "source_ids": ["src_ilo", "src_gov_1"] }
#     },
#     "next_steps": [
#       "Interview 10 to 15 freelancers to confirm willingness to pay.",
#       "Replace the assumed CAC and churn with figures from a small pilot.",
#       "Review GST and data-protection obligations with a professional."
#     ]
#   },
#   "sources": [
#     { "id": "src_wb_1", "name": "World Bank Indicators API: SL.EMP.SELF.ZS", "type": "structured_api", "url": "https://api.worldbank.org/v2/country/IN/indicator/SL.EMP.SELF.ZS?format=json", "license": "CC BY 4.0", "retrieved_at": "2026-10-15", "used_for": ["market", "macro"] },
#     { "id": "src_wb_2", "name": "World Bank Indicators API: NY.GDP.MKTP.KD.ZG", "type": "structured_api", "url": "https://api.worldbank.org/v2/country/IN/indicator/NY.GDP.MKTP.KD.ZG?format=json", "license": "CC BY 4.0", "retrieved_at": "2026-10-15", "used_for": ["macro"] },
#     { "id": "src_wb_3", "name": "World Bank Indicators API: FP.CPI.TOTL.ZG", "type": "structured_api", "url": "https://api.worldbank.org/v2/country/IN/indicator/FP.CPI.TOTL.ZG?format=json", "license": "CC BY 4.0", "retrieved_at": "2026-10-15", "used_for": ["macro"] },
#     { "id": "src_ilo", "name": "ILOSTAT wage data", "type": "structured_api", "url": "https://ilostat.ilo.org/data/", "license": "See provider terms", "retrieved_at": "2026-10-15", "used_for": ["cost"] },
#     { "id": "src_bls", "name": "US BLS Business Employment Dynamics", "type": "structured_api", "url": "https://www.bls.gov/bdm/", "license": "US public domain", "retrieved_at": "2026-10-15", "used_for": ["survival_funding"] },
#     { "id": "src_hn", "name": "Hacker News (Algolia Search API)", "type": "community", "url": "https://hn.algolia.com/api/v1/search", "license": "See provider terms", "retrieved_at": "2026-10-15", "used_for": ["pain", "demand"] },
#     { "id": "src_se", "name": "Stack Exchange API", "type": "community", "url": "https://api.stackexchange.com/2.3/search/advanced", "license": "Attribution required", "retrieved_at": "2026-10-15", "used_for": ["pain", "demand"] },
#     { "id": "src_yt", "name": "YouTube Data API v3 (comments)", "type": "community", "url": "https://www.googleapis.com/youtube/v3/commentThreads", "license": "See provider terms", "retrieved_at": "2026-10-15", "used_for": ["pain"] },
#     { "id": "src_as", "name": "Apple iTunes Search API and public review feed", "type": "reviews", "url": "https://itunes.apple.com/search", "license": "See provider terms", "retrieved_at": "2026-10-15", "used_for": ["pain"] },
#     { "id": "src_wiki", "name": "Wikimedia Pageviews API", "type": "structured_api", "url": "https://wikimedia.org/api/rest_v1/", "license": "CC0 data", "retrieved_at": "2026-10-15", "used_for": ["demand"] },
#     { "id": "src_vertex", "name": "Vertex AI Search over public competitor and pricing pages", "type": "web_pages", "url": "https://example.com/a/pricing", "license": "Page-level; cited, not reproduced", "retrieved_at": "2026-10-15", "used_for": ["competition", "unit_economics", "cost"] },
#     { "id": "src_gov_1", "name": "Official registration and regulatory portals (via Vertex)", "type": "web_pages", "url": "https://example.gov/registration-fees", "license": "Government publication", "retrieved_at": "2026-10-15", "used_for": ["cost", "regulatory"] }
#   ],
#   "data_quality": {
#     "value_labels": { "sourced": 14, "estimated": 19, "assumed": 9 },
#     "parameters_scored": 8,
#     "parameters_insufficient": ["survival_funding"],
#     "evidence_items_total": 412,
#     "evidence_items_used": 63,
#     "oldest_data_year": 2024,
#     "limitations": [
#       "Free sources lack competitor revenue, traffic, funding, CAC and churn.",
#       "Community sources skew technical and English-speaking.",
#       "Rent and equipment prices are low-confidence regional estimates."
#     ]
#   },
#   "generation": {
#     "pipeline_version": "1.0",
#     "llm_provider": "sarvam",
#     "llm_model": "sarvam-105b-conversations",
#     "llm_calls": { "plan": 1, "classification_batches": 15, "summary": 1 },
#     "duration_seconds": 212
#   },
#   "disclaimer": "This report supports, but does not replace, primary customer research. Scores are directional estimates, not probabilities of success."
# }


# ----------- Explanation of how to use it ------------

# 1. What Each Top-Level Block Is For

# idea: the normalised input, including the business type and country code produced in Stage 2. The frontend shows it as the report header.
# overall: the headline Viability Score, band, and confidence, plus a per-parameter breakdown for a chart, and the strengths and risks.
# parameters: the detail behind each of the nine parameters, with the evidence, calculations, and caveats.
# assumptions: every editable input. The user can change one, and the affected figures are recalculated by code.
# narrative: the Stage 9 LLM text, which must be written only from the structured fields and must cite source IDs.
# sources: the citation list, with the licence and retrieval date. This is where attribution requirements are met.
# data_quality and generation: transparency and audit data.

# 2. Which Sources Feed Which Part

# Pain: Hacker News, Stack Exchange, YouTube, App Store reviews, and grounded search feed the counts, themes, and evidence.
# Market: World Bank, OECD, and national statistics feed the TAM inputs and growth. Your assumption table supplies the SAM and SOM shares.
# Demand: Wikipedia pageviews and mention counts from Hacker News and Stack Exchange feed the demand series.
# Competition, pricing, and cost: Vertex search over public pages feeds the competitor table, price benchmarks, and software costs. ILOSTAT-style wage data feeds salaries.
# Regulatory: official portals reached through Vertex.
# Survival and funding: BLS appears only as a reference benchmark.
# Macro: World Bank indicators.

# 3. Design Decisions Worth Noting

# All parameter scores point the same way (higher is more favourable). A high competition score means less crowded, and a high cost score means lower burden.
# Missing data stays visible. survival_funding is insufficient_data, and its weight is redistributed to the other parameters (effective_weight), so the overall score is not dragged down by something that could not be measured.
# Every figure carries a label (sourced, estimated, or assumed) and source_ids, so the frontend can show provenance and the summary writer cannot present an assumption as fact.
# Ranges, not single numbers, for TAM, SAM, SOM, and cost, because the inputs are low to medium confidence.
# Nulls instead of guesses. Competitor revenue and funding are null because free sources cannot supply them.

# 4. What Free Sources Cannot Show

# Competitor revenue, traffic, and funding.
# Real CAC, churn, and conversion rates (these stay as editable assumptions).
# Local rent and equipment prices.
# Sector survival and seed-funding data for most countries.
# Official Google Trends search interest (shown as unavailable).

# 5. Status and Caveats

# Illustrative values. All numbers, competitor names, and URLs are placeholders. Do not treat the indicator values as real statistics.
# Only the pain formula exists in code. The pain components match pain_point_pipeline.py and reproduce the 69.0 score. The component values for the other parameters are placeholders until their scoring formulas are written, along with the Stage 8 aggregation and Stage 9 summary code.
# Checks performed: The JSON parses and is internally consistent. I verified the overall score (61.68, shown as 61.7), the TAM/SAM/SOM arithmetic, LTV and break-even, the cost totals, the theme and source counts, and that every source_ids reference resolves.
# Rounding. effective_weight is rounded to four decimals, so the weights sum to 1.0001 instead of exactly 1.