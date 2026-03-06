# Evidence Base for "The Rise of Organizational Memories"

**The evidence assembled here supports five numbered positions arguing that the field needs "Organizational World Models" as its North Star — systems that predict organizational consequences, not merely retrieve documents.** This brief draws on 120+ verified sources across organizational theory, cognitive science, data engineering, AI/ML systems, information theory, and industry practice. Every citation is real and verifiable. The evidence is organized first by position, then cross-referenced by evidence type.

---

## Position #1: Structured data was built for dumb readers

The entire edifice of modern data engineering — normalization, star schemas, ETL pipelines — was designed to compensate for the limitations of downstream consumers, not to reflect some Platonic ideal of data organization. The historical record is unambiguous.

### The relational model optimized for machine readers, not reality

Edgar Codd's 1970 paper "A Relational Model of Data for Large Shared Data Banks" (*Communications of the ACM*, 13(6), 377–387) introduced normalization explicitly to achieve **"data independence"** — separating logical organization from physical storage so that simple query engines could navigate data without understanding context. Normal forms (1NF through 6NF) each eliminate a class of redundancy, but redundancy in the information-theoretic sense often carries contextual information. First normal form forces atomic values, discarding embedded structure. Second normal form removes partial dependencies, forcing decomposition. Third normal form severs transitive dependencies — implicit relationships that a human reader would naturally understand. Each step makes data more amenable to simple SQL readers while stripping contextual richness.

Ralph Kimball's dimensional modeling (first formalized in *The Data Warehouse Toolkit*, 1996) was designed even more explicitly for reader limitations. As Holistics documents, "In the early 1990s, Ralph Kimball and his team created data marts to analyze retail sales figures. Facing the ER model query problem head-on, the team realized that all business questions could be framed as a simple process: 'Measure by Context.'" Star schemas existed because **BI tools of the 1990s could not execute complex joins efficiently** — denormalization traded storage redundancy for read performance on limited hardware. Joe Reis confirms this lineage while arguing for its continued relevance: "Is Kimball still relevant? Absolutely. It's a battle-hardened, time-tested way to model data for analytics" (Substack, July 2023).

Bill Inmon, the "father of data warehousing," defined a data warehouse as "a subject-oriented, nonvolatile, integrated, time-variant collection of data in support of management's decisions" (*Building the Data Warehouse*, 1992). The key phrase is "in support of management's decisions" — the entire architecture was downstream-consumer-driven.

### ETL as reader-capability compensation

ETL (Extract, Transform, Load) pipelines exist because downstream consumers — dashboards, BI tools, reporting engines — could not interpret raw operational data. As one industry analysis notes: "This heavy upfront transformation made sense at the time: storage was expensive and compute was limited." The **shift from ETL to ELT** (Extract, Load, Transform) in the cloud era is itself evidence that reader capability drives architecture. Maxime Beauchemin (creator of Apache Airflow, formerly at Facebook and Airbnb) summarized the logic: "Compute is cheap. Storage is cheap. Engineering time is expensive." Cloud data warehouses like Snowflake and BigQuery perform transformations at query time because they *can* — their read-side intelligence increased.

James Dixon, CTO of Pentaho, coined "data lake" in October 2010 with an explicit reader-capability argument: "If you think of a Data Mart as a store of bottled water, cleansed and packaged and structured for easy consumption, the Data Lake is a large body of water in a more natural state." The lakehouse architecture (Armbrust et al., "Lakehouse: A New Generation of Open Platforms that Unify Data Warehousing and Advanced Analytics," CIDR 2021) represents another step: combining raw storage with increasingly intelligent query engines.

### The information-theoretic argument: schemas are lossy compression

George Box's famous aphorism — **"All models are wrong, but some are useful"** (Box & Draper, 1987, *Empirical Model-Building and Response Surfaces*, p. 424; earlier in Box, 1976, "Science and Statistics," *JASA*, 71, 791–799) — applies directly. Every database schema is an ontological commitment about what matters and what doesn't. It is a model of reality, and by Box's principle, it is wrong — the question is *how* wrong, and for *whom*.

Shannon's rate-distortion theory (Shannon, 1959, "Coding Theorems for a Discrete Source with a Fidelity Criterion," *IRE National Convention Record*, Part 4, 142–163) provides the mathematical framework. The rate-distortion function R(D) = min I(X;Y) subject to E[d(x,y)] ≤ D gives the minimum bits needed to represent a source at a given distortion level. The critical insight for this paper: **the distortion measure d(x,y) is reader-dependent**. A human analyst reading a denormalized table has high distortion tolerance for unstructured text — so we structure heavily. An LLM has low distortion for unstructured text — so less structure is needed. As reader intelligence increases, the effective distortion function changes, shifting the R(D) curve.

A recent paper directly applies this framework: An et al. (2024), "Rate-Distortion Guided Knowledge Graph Construction from Lecture Notes Using LLMs" (arXiv:2511.14595), treats knowledge graphs as compressed representations and finds the R-D curve exhibits a **"knee point" where 50% distortion reduction requires only 30% of total rate cost**. Beyond the knee, additional structure yields diminishing returns.

The Minimum Description Length principle (Rissanen, 1978, "Modeling by shortest data description," *Automatica*, 14(5), 465–471) formalizes this further: L_total = L(model) + L(data|model). A more intelligent decoder (LLM) can reconstruct more from less structure, shifting the optimal balance point.

---

## Position #2: Reader intelligence has increased by orders of magnitude

### Scaling laws predict continued growth in reader capability

Kaplan et al. (2020), "Scaling Laws for Neural Language Models" (arXiv:2001.08361, OpenAI), demonstrated that LLM loss scales as a **power-law** with model size, dataset size, and compute, spanning more than seven orders of magnitude. The key exponents: L(N) ≈ (Nc/N)^0.076 for model size and L(D) ≈ (Dc/D)^0.095 for data. These are not speculative — they are empirically validated curves that predict reader intelligence as a smooth, increasing function of investment.

Hoffmann et al. (2022), "Training Compute-Optimal Large Language Models" (NeurIPS 2022, arXiv:2203.15556, DeepMind) — the Chinchilla paper — refined this: for compute-optimal training, model size and training tokens should scale equally (N_opt ∝ C^0.5, D_opt ∝ C^0.5). Chinchilla (70B parameters) outperformed models 4× larger by being better trained. This means reader intelligence increases *and* inference cost decreases simultaneously.

### The compression-intelligence equivalence

Delétang et al. (2024), "Language Modeling Is Compression" (ICLR 2024), proved that any predictive model can be transformed into a lossless compressor and vice versa, with LLMs outperforming traditional compression tools like gzip. Huang et al. (2024), "Compression Represents Intelligence Linearly" (arXiv:2404.09937), found across **30 public LLMs and 12 benchmarks** a linear correlation between compression efficiency and benchmark performance. If intelligence ≈ compression ability, and LLMs are increasingly powerful compressors that scale predictably, then the "reader" in our data system is becoming a fundamentally better *decompressor* — tolerating more lossy encoding, requiring less write-time structure.

### Cost curves are crossing

Inference costs are collapsing. Epoch AI (2025) found that the price to achieve GPT-4-level performance fell by **~40× per year**. Andreessen Horowitz ("Welcome to LLMflation," 2024) documented a **1,000× cost reduction in 3 years**: what cost $60/million tokens in 2021 (GPT-3) costs $0.06/million tokens today at equivalent capability. Meanwhile, data engineering costs are rising: the global ETL market reached **$7.6–8.9 billion in 2026** (SNS Insider, Mordor Intelligence), organizations spend **$520,000 annually** on custom data pipelines (Wakefield Research/Fivetran), and Gartner estimates poor data quality costs **$12.9 million per organization per year**. The crossover is approaching: it will be cheaper to have intelligent readers interpret unstructured data than to structure it at write time.

### Empirical evidence of LLM capability with messy data

A 2025 European Journal of Computer Science and IT study found LLM-assisted ETL **reduced pipeline development from 13.7 to 6.8 person-days**, achieved 97.4% accuracy on tourism data across 17 sources, and outperformed rule-based approaches for regulatory requirement extraction (93% vs. lower baselines). UC Berkeley's DocETL project demonstrated "declarative operators amenable to powerful optimization, improving accuracy in large-scale, complex document analysis tasks." IBM reports that **80%+ of enterprise data is unstructured** — and LLMs are the first technology that can process this data at scale.

### The structured-data advocates push back

Chad Sanderson (CEO of Gable.ai, author of *Data Contracts*, O'Reilly) argues data quality is *more* critical in the AI era: "The quality of data is as crucial as the AI model itself. He pointed out challenges in AI models related to a lack of high quality data, including incorrect predictions, model outages, and 'hallucinations'" (Harvard D^3 Institute, Nov 2023). Sanderson identifies four root causes of poor data quality: lack of producer ownership, limited awareness of downstream usage, absence of change management, and lack of semantic agreement.

Joe Reis (co-author, *Fundamentals of Data Engineering*, O'Reilly, 2022) has directly addressed the "modeling is dead" argument. In "Data Modeling is Dead (Again) — 2026 Edition" (Practical Data Modeling Substack, Dec 2025), he catalogued and dismantled common AI-era arguments including "Context Window is the New Schema" and "Tabular Data is Dead," concluding: "AI actually *increases* the need for rigorous data modeling, rather than replacing it." He warns of "a growing sentiment that the tech industry might be making a 'big self-own' by relying too heavily on AI without adequately training a new generation of engineers."

The GIGO argument has empirical weight: University of Naples (2025) found that removing 5% of flawed Python code from training data reduced LLM-generated code errors from 5.8% to 2.2%. Clean Markdown improves RAG retrieval accuracy by up to 35% (AnythingMD). MIT Technology Review (Jan 2026) quotes: "You can only utilize unstructured data once your structured data is consumable and ready for AI."

**The emerging synthesis** — and the paper's opportunity — is that both camps are partially right but framing the wrong question. The debate is not "structure vs. no structure" but "who does the structuring and when." Ananth Packkildurai (Data Engineering Weekly) captures this: "The irreducible work was never about moving data. It was always about meaning."

---

## Position #3: No consensus exists on "organizational memory"

### The foundational framework is 35 years old and pre-digital

Walsh & Ungson (1991), "Organizational Memory" (*Academy of Management Review*, 16(1), 57–91), provided the first integrative framework, defining organizational memory as **information acquisition, retention, and retrieval** distributed across five "retention bins": individual memory, culture, transformations (routines/processes), structure (roles/hierarchy), and ecology (physical environment), plus external archives. Anderson & Sun (2010) documented 300+ subsequent citations but noted the framework has been critiqued for treating memory as a "storage bin" — a repository metaphor that maps poorly onto dynamic, AI-augmented knowledge systems.

Daniel Wegner's transactive memory systems (1987, "Transactive Memory: A Contemporary Analysis of the Group Mind," in *Theories of Group Behavior*, Springer) described how groups create cognitive division of labor: members specialize and remember **"who knows what"** rather than storing everything individually. Ren & Argote (2011) reviewed 76 papers in *Academy of Management Annals*, framing TMS as a microfoundation of dynamic capabilities. This concept maps naturally onto AI-augmented organizational memory — but no agreed-upon framework connects TMS to modern AI architectures.

Nonaka & Takeuchi (1995, *The Knowledge-Creating Company*, Oxford University Press) introduced the SECI model (Socialization, Externalization, Combination, Internalization) for tacit-explicit knowledge conversion. Their key insight: "Tacit knowledge is highly personal and hard to formalize, making it difficult to communicate or to share with others." The SECI model remains "widely acknowledged as a theoretical landmark" (Farnese et al., 2019, *Frontiers in Psychology*), but it was designed for Japanese manufacturing firms, not AI-augmented digital organizations.

### Vendors, academics, and practitioners use different definitions

The subagent research confirmed a fragmented landscape. Some mean **RAG** when they say organizational memory (the retrieval-augmented generation community). Some mean **knowledge graphs** (enterprise architecture and semantic web communities). Some mean **long-context LLMs** (the "just put everything in context" camp). Some mean **enterprise search** (Glean, Coveo, Elastic). Some mean **persistent agent memory** (MemGPT/Letta, Mem0). Some mean **digital twins of organizations** (Skan AI, Transentis). Microsoft Copilot treats it as personal memory within organizational data. Google NotebookLM treats it as source-grounded document analysis.

No paper was found explicitly titled "organizational world model" in the AI/ML literature. The concept sits at an unoccupied intersection of enterprise digital twins, organizational knowledge graphs, agentic AI memory systems, and world models from robotics/RL. This represents a genuine gap.

### Organizational forgetting compounds the definitional problem

Martin de Holan & Phillips (2004), "Remembrance of Things Past? The Dynamics of Organizational Forgetting" (*Management Science*, 50(11), 1603–1613), defined organizational forgetting as "the non-intentional process of organizations losing previously acquired knowledge and/or practices" and developed a 2×2 typology (accidental/intentional × new/established knowledge). Their MIT Sloan Management Review article (2004) warned: "The involuntary loss of organizational knowledge is costing companies millions of dollars every year." Any definition of organizational memory must account for forgetting — yet most AI-era definitions ignore this entirely.

---

## Position #4: Every existing approach solves only part of the problem

### RAG: seven documented failure points

Lewis et al. (2020), "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (NeurIPS 2020), introduced the foundational architecture. But Barnett et al. (2024), "Seven Failure Points When Engineering a Retrieval Augmented Generation System" (IEEE/ACM CAIN 2024, arXiv:2401.05856), systematically identified failures across three domains: **(1) missing content**, (2) missed top-K chunks, **(3) context fragmentation** where critical information splits across chunks, (4) extraction failure, (5) wrong format, (6) incorrect specificity, and (7) incompleteness. Their key conclusion: "Validation of a RAG system is only feasible during operation, and the robustness of a RAG system evolves rather than designed in at the start." IBM's Nirmal described the chunking problem vividly: "You chunked, or you cut off, in the middle of a table, so when you bring back the table, you bring half of the table."

### Vector databases: mathematically bounded

Weller et al. (2025), "On the Theoretical Limitations of Embedding-Based Retrieval" (arXiv:2508.21038, Google DeepMind), proved that single-vector embedding models have a **fundamental capacity limit** — the number of possible top-k retrieval results is bounded by the embedding dimension. This is not a training issue but a mathematical constraint. Their LIMIT dataset stress test showed even state-of-the-art models (Gemini Embeddings, GritLM) "severely struggle," failing to reach 20% recall@100. The decades-old lexical method BM25 outperformed neural embeddings on compositional queries. Writer.com documents the update cost problem: "Every time you need to add new data, a vector database needs to rerun all the data and assign each data object a new value."

### Knowledge graphs: promising but brittle in practice

Gartner (Pal, 2022) warned that "barriers to entry are high and often daunting." Gartner (Jaffri, 2024) counseled against enterprise-wide schema design: "Such endeavors are costly, time-consuming, filled with disagreement and, in many cases, stopped before any value can be shown." Enterprise Knowledge found that **"few have successfully deployed an enterprise knowledge graph that proves out the true business value and ROI."** Matt Aslett (ISG Research) noted: "I've been in the data space for 20 years, and for at least half of it, people have been trying to make knowledge graphs the way to go." The 2024 Gartner Hype Cycle placed GraphRAG halfway up the slope of inflated expectations, 2–5 years from maturity.

### Long-context LLMs: impressive windows, unreliable utilization

Liu et al. (2024), "Lost in the Middle: How Language Models Use Long Contexts" (*TACL*, 12, 157–173), demonstrated that **performance degrades significantly when relevant information appears in the middle of long contexts**, even for explicitly long-context models. Hong, Troynikov & Huber (2025), "Context Rot" (Chroma Research), evaluated 18 LLMs including GPT-4.1, Claude 4, and Gemini 2.5, finding "models do not use their context uniformly; instead, their performance grows increasingly unreliable as input length grows." Laban et al. (2024), "Summary of a Haystack" (EMNLP 2024), found that **without a retriever, long-context LLMs score below 20%** on summarization tasks, and even with oracle signals they lag human performance by 10+ points. Context window size ≠ effective utilization. Gemini offers 1M tokens, Llama 4 claims 10M, but reliable performance at these lengths remains unproven.

### Enterprise search: discovery without memory

Glean, the leading AI-powered enterprise search platform (1,000+ enterprise customers), connects 100+ data sources and applies generative summarization. Yet Coworker.ai's evaluation concluded: "If your bottleneck is execution, orchestration, or long-term organizational memory, you should expect to layer additional capabilities." They analogized: "Picture Glean like a high-powered metal detector on a crowded beach: it finds the coin quickly, but it does not dig, catalogue, and store the collection for you." Slite's review noted Glean "might give you obsolete results from docs that are 3 years old" due to lacking knowledge verification. Moveworks documented that "employees spend nearly 20 percent of their workweek searching for information" and that "traditional enterprise search was built to retrieve documents, not to understand intent or guide next steps."

### The cross-cutting failure: no system captures tacit knowledge or organizational dynamics

All five approaches operate exclusively on explicit, documented information. Nonaka and Takeuchi's tacit knowledge — the informal knowledge of why decisions were made, what was tried and failed, who knows what — remains uncaptured. No current system models organizational *state* (who is working on what, what decisions are pending, how teams relate to each other) or predicts consequences of organizational actions.

---

## Position #5: The "Organizational World Model" fills a real gap

### Cognitive science grounds the concept

Kenneth Craik (1943, *The Nature of Explanation*, Cambridge University Press) proposed that thinking involves building **"small-scale models" of reality** for prediction: "One of the most fundamental properties of thought is its power of predicting events. This gives it immense adaptive and constructive significance." Craik described three processes: translation of external processes into internal representations, derivation of new symbols by inference, and retranslation back to external processes.

Karl Friston's free energy principle (2010, "The free-energy principle: A unified brain theory?" *Nature Reviews Neuroscience*, 11(2), 127–138, 6,400+ citations) proposes the brain minimizes prediction error through perception (updating models) and action (changing the world to match predictions). Andy Clark's *Surfing Uncertainty* (2016, Oxford University Press) characterizes the brain as a hierarchical prediction machine generating top-down expectations and propagating only prediction errors upward.

Daniel Schacter's work on constructive memory (2012, "Adaptive constructive processes and the future of memory," *American Psychologist*, 67(8), 603–613) provides perhaps the most direct bridge: "Simulating future events relies on many of the same cognitive and neural processes as remembering past events." Memory is not a retrieval system — it is a **prediction system** that reconstructs the past in service of simulating the future. Bartlett (1932, *Remembering*, Cambridge University Press) established this empirically: memory is "an imaginative reconstruction or construction" shaped by schemas and current demands.

### AI world models provide the technical foundation

Yann LeCun (2022, "A Path Towards Autonomous Machine Intelligence," OpenReview) proposed a six-module cognitive architecture centered on a **world model** whose role is "(1) estimate missing information about the state of the world not provided by perception, (2) predict plausible future states of the world." His Joint Embedding Predictive Architecture (JEPA) learns predictable abstract representations, ignoring unpredictable details. Goldfeder, Wyder, LeCun & Shwartz-Ziv (2026), "AI Must Embrace Specialization via Superhuman Adaptable Intelligence" (arXiv:2602.23643), extended this argument: "World models enable simulation and planning, which are the hallmark of zero-shot and few-shot adaptation." They introduced Superhuman Adaptable Intelligence (SAI) — intelligence that learns to exceed humans at specific important tasks — grounded in world models and self-supervised learning.

### The emerging architectural components

**MemGPT/Letta** (Packer et al., 2023, "MemGPT: Towards LLMs as Operating Systems," arXiv:2310.08560) introduced hierarchical memory management for AI agents — core memory (always in-context), recall memory (searchable conversation history), and archival memory (long-term vector-searchable storage). The system has evolved into a full platform with sleep-time compute (Lin et al., 2025, arXiv:2504.13171), where agents process and reorganize memory during idle time, **reducing test-time compute by ~5×** while maintaining accuracy. This is directly relevant: an organizational world model would continuously refine its understanding of organizational state.

**Mem0** (Chhikara et al., 2025, arXiv:2504.19413) provides a production memory layer with 41K+ GitHub stars and 186M API calls in Q3 2025, using hybrid graph-vector-KV stores. **Microsoft GraphRAG** (Edge et al., 2024, arXiv:2404.16130) combines LLM-generated knowledge graphs with community detection and hierarchical summarization, addressing RAG's failure to connect disparate information.

**Enterprise digital twins** are emerging but lack the reasoning layer. Salesforce's eVerse simulates customer interactions. Skan AI proposes "Digital Twin of an Organization" capturing processes, people, and decisions. Transentis combines ArchiMate enterprise modeling with Neo4j and GPT for "AI-powered enterprise digital twins." Viven.ai (launched Oct 2025) creates digital twins of individual employees. But none of these systems builds a causal, predictive model of organizational dynamics.

### Bounded rationality defines the metric

Herbert Simon (1955, "A behavioral model of rational choice," *Quarterly Journal of Economics*, 69(1), 99–118; 1957, *Models of Man*, Wiley) established that organizations exist to compensate for bounded rationality — "replacing the global rationality of economic man with rational behavior compatible with the access to information and computational capacities actually possessed by organisms." His scissors metaphor — one blade is cognitive limitation, the other is environmental structure — implies that an organizational world model serves as a prosthetic blade, extending the cognitive reach of decision-makers.

The information overload literature reinforces this. Eppler & Mengis (2004, *The Information Society*, 20(5), 325–344) defined the threshold: "After a certain point, the decision-maker has obtained more information than he can process, information overload has occurred and decision-making ability decreases." Iselin (1989, *Journal of Information Science*) found decision performance falls beyond approximately **10 items of information**. An organizational world model compresses complex organizational reality into actionable predictions, directly addressing overload. **Decision latency reduction** — how much faster leaders reach good decisions — is the natural metric because it captures both the compression quality and the prediction accuracy of the model.

---

## Concrete exemplars that make the argument vivid

### NASA: the $200B knowledge asset that evaporated

When the Constellation program attempted to return to the Moon, "a painful reality became quickly evident — NASA would first have to relearn how to conduct a manned mission to the moon. The organization had forgotten some of the essential knowledge needed. Plans had been lost, and essential personnel had since retired or moved on" (MIT Sloan Management Review). David Oberhettinger, JPL's Chief Knowledge Officer, noted: "No one thought to keep a copy of the drawing and design data for the gargantuan Saturn 5 rocket." In 2015, NASA's Orion team needed Apollo-era uprighting system lessons; enterprise search at Johnson Space Center "did not turn up any information, so the team spent months asking retired engineers." At a commemorative event, only **~5% of JSC employees had worked during the Apollo era** (IEEE Spectrum, 2017).

### Boeing: when cost-cutting destroyed process knowledge

Bloomberg (June 2019) reported that Boeing's 737 MAX software "was developed at a time Boeing was laying off experienced engineers and pressing suppliers to cut costs," relying on "temporary workers making as little as $9 an hour." The MCAS system failure killed **346 people** across two crashes. A former union head recalled a staffer complaining about "sending drawings back to a team in Russia 18 times before they understood that the smoke detectors needed to be connected to the electrical system." Former CEO Harry Stonecipher's proclaimed intent to run Boeing "like a business rather than a great engineering firm" exemplifies knowledge-destroying cultural transformation.

### The Challenger disaster: normalization of deviance as memory pathology

Diane Vaughan (*The Challenger Launch Decision*, University of Chicago Press, 1996) documented how NASA's organizational memory gradually normalized risk: the O-ring concern evolved from a launch-stopper to accepted risk through "a long incubation period with early warning signs that were either misinterpreted, ignored or missed completely." Richard Feynman's analogy captured the pathology: "Try playing Russian roulette that way: you pull the trigger and the gun doesn't go off, so it must be safe to pull the trigger again." When Columbia disintegrated in 2003, the investigation board "echoed the Challenger findings" — the same organizational memory failure had repeated 17 years later.

### The Google Effect: transactive memory meets search

Sparrow, Liu & Wegner (2011), "Google Effects on Memory" (*Science*, 333(6043), 776–778), demonstrated that **when people expect future access to information, recall of the information itself drops** (from 31% to 22%) while recall of *where to find it* increases. The Internet became "a primary form of external or transactive memory." At the organizational level, this creates a dangerous assumption: knowledge is "somewhere in the system" — until it isn't, as NASA discovered.

### 9/11: the catastrophic cost of information silos

The 9/11 Commission Report (2004) concluded the attacks represented a **"failure to connect the dots"** — pieces of the puzzle existed across agencies but "no one connected the dots well enough or in a timely enough manner." Information was kept in "agency silos" (stovepipes) blocked by legal and cultural barriers. The structural response — creating ODNI and DHS, combining 22 organizations — acknowledged that the problem was organizational memory architecture, not intelligence gathering capability.

### Morgan Stanley: the AI retrieval paradigm shift

Morgan Stanley became the first major Wall Street firm to deploy GPT-4 at scale (September 2023), enabling advisors to query **100,000+ research documents**. Jeff McMillan reported: "We went from being able to answer 7,000 questions to a place where we can now effectively answer any question." Document retrieval efficiency jumped from **20% to 80%**. McMillan's key insight captures the thesis: "This technology makes you as smart as the smartest person in the organization." **98% of advisor teams** now actively use the system.

---

## Authority-versus-authority evidence map

### The structured data advocates

- **Chad Sanderson** argues data contracts are "absolutely ESSENTIAL to scale data governance and data quality to the software engineering organization." His position: AI amplifies data quality problems, so preventive infrastructure (shifting quality checks left, toward data producers) becomes more important, not less.
- **Joe Reis** warns the industry is "making a 'big self-own' by relying too heavily on AI without adequately training a new generation of engineers." His December 2025 post directly dismantles "Context Window is the New Schema," "One Big Table," and "Tabular Data is Dead" arguments. Position: AI increases the need for data modeling.
- **Bill Inmon** emphasizes: "Modern technology depends on a solid foundation of data... Yet there is no such foundation of data that exists in the corporation that is believable." Position: You need structure before intelligence.
- **The Kimball tradition**: dimensional modeling was designed for reader limitations but remains useful because it imposes semantic discipline. Reis: "To say Kimball is irrelevant because of columnar storage and unlimited compute is a dangerously ignorant statement."

### The AI-native advocates

- **Ananth Packkildurai** (Data Engineering Weekly) proposes replacing ETL with ECL (Extract, Contextualize, Link), arguing "The irreducible work was never about moving data. It was always about meaning." But he also warns that "bad contracts are amplified at scale" by AI agents.
- **UC Berkeley's DocETL team** demonstrates LLM-powered pipelines processing documents beyond context limits through decomposition.
- **Unstract** positions LLMs as a "bridge" converting unstructured to structured — though they concede LLMs are "not yet the silver bullet for unstructured data processing."

### RAG vs. long-context debaters

The RAG community (Lewis et al. lineage) argues retrieval-augmentation provides grounding and verifiability. The long-context community argues putting everything in context eliminates retrieval errors. The evidence shows both fail: RAG has seven documented failure points (Barnett et al., 2024), while long-context models exhibit "context rot" (Hong et al., 2025) and score below 20% on summarization without retrieval (Laban et al., 2024). GraphRAG (Edge et al., 2024) represents an attempted synthesis, but Gartner places it 2–5 years from maturity.

---

## Current state of the art (2024–2026): the pieces exist but are unassembled

The landscape as of early 2026 comprises five categories that do not yet converge:

- **Memory systems** (MemGPT/Letta, Mem0) provide persistence but lack organizational structure. Mem0 has 41K GitHub stars and AWS partnership but operates at the individual agent level, not the organizational level.
- **Knowledge retrieval** (GraphRAG, Microsoft Graph, Glean) indexes organizational data but doesn't model dynamics or predict consequences. Microsoft Copilot reached only ~8M paying subscribers (1.8% of M365 users) by August 2025, with Gartner finding only 5% of organizations moved from pilot to full deployment.
- **Enterprise digital twins** (Skan AI, Transentis, Salesforce eVerse) model processes and operations but lack LLM-powered reasoning and causal prediction.
- **Productivity tools** (Google NotebookLM, Notion AI) provide individual or small-team knowledge augmentation but not shared organizational understanding. NotebookLM's 1M-token context window and source-grounding are powerful but notebook-scoped.
- **World models in AI** (LeCun's JEPA, Dreamer, Genie) operate in physical or game domains, not organizational contexts. The Goldfeder et al. (2026) SAI paper provides the intellectual foundation — world models enable adaptation through simulation and planning — but does not apply this to organizations.

McKinsey's "The Agentic Organization" (2025) projects AI task completion length doubling every 4 months, reaching ~2 hours of autonomous work by late 2025, with projections of 4 days by 2027. Gartner predicts intelligent simulation will underpin over 25% of strategic business decisions by 2032. The World Economic Forum (Feb 2026) identifies structural redesign, not just technology adoption, as the bottleneck. The convergence is happening — but no one has named the destination.

### The gap this paper fills

The Hu et al. (2025) survey "Memory in the Age of AI Agents" (arXiv:2512.13564, 46+ authors) taxonomizes agent memory into factual, experiential, and working memory — but treats agents as individual entities, not organizational systems. The Letta team's sleep-time compute and context repositories provide architectural primitives. GraphRAG provides knowledge structure. Enterprise digital twins provide organizational modeling. But no existing system combines all four into a unified **organizational world model** that maintains dynamic state, captures causal relationships, and predicts consequences of organizational decisions. The metric of decision latency reduction — measuring how much faster leaders reach good decisions — connects directly to Simon's bounded rationality framework and provides an empirically measurable evaluation criterion.

---

## Conclusion: the evidence supports a novel synthesis

The historical evidence establishes that data engineering architectures were downstream-consumer-driven artifacts. The scaling law evidence demonstrates reader intelligence is increasing predictably and its cost is declining exponentially. The organizational theory literature provides rich frameworks (Walsh & Ungson, Wegner, Nonaka & Takeuchi) that predate AI but map naturally onto new architectures. The cognitive science evidence — from Bartlett's reconstructive memory through Craik's world models to Friston's predictive processing — establishes that memory-as-prediction is more biologically and computationally sound than memory-as-retrieval. The systematic documentation of failure modes across RAG, vector databases, knowledge graphs, long-context LLMs, and enterprise search confirms that no current approach provides a coherent whole. And the vivid examples — NASA, Boeing, Challenger, 9/11 — demonstrate that organizational memory failure carries catastrophic real-world consequences that justify ambitious new frameworks. The concept of an Organizational World Model is not present in the current literature, creating a genuine opportunity for a landmark contribution.