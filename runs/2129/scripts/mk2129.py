import json, hashlib, subprocess, sys
R = "/Users/andy/Downloads/Junction2/receipts"
REPO = "/Users/andy/Downloads/Junction2/repo"
HEAD = "origin/ju26-issue-2129"
NOW = "2026-11-14T23:50"
cache = {}
def lines(p):
    if p not in cache:
        cache[p] = subprocess.check_output(["git", "-C", REPO, "show", f"{HEAD}:{p}"], text=True).splitlines()
    return cache[p]
def cite(p, q):
    for i, t in enumerate(lines(p), 1):
        if q in t:
            return {"path": p, "line": i, "quote": q}
    raise SystemExit(f"quote not found in {p}: {q}")
A = "src/MessagePack.Annotations/Attributes.cs"
G = "src/MessagePack.SourceGenerator/MessagePackGenerator.cs"
C = "src/MessagePack.SourceGenerator/CodeAnalysis/GeneratedFormatterCollector.cs"
U = "src/MessagePack.SourceGenerator/GeneratorUtilities.cs"
T = "src/MessagePack.SourceGenerator/Transforms/FormatterTemplate.tt"
E = "tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypesTests.cs"
D = "tests/MessagePack.SourceGenerator.Tests/GeneratedMessagePackFormatterTests.cs"
FX = "tests/MessagePack.SourceGenerator.ExternalTypes/MessagePack.SourceGenerator.ExternalTypes.csproj"
RM = "README.md"
AR = "src/MessagePack.SourceGenerator/AnalyzerReleases.Unshipped.md"
IX = "doc/analyzers/index.md"
EP = "tests/MessagePack.SourceGenerator.ExternalTypes/ExternalPerson.cs"

meta = lambda kind, prompt=None, sha=None: {
    "change": "2129", "kind": kind, "produced_by": "claude-code session, cached", "model": "claude-sonnet-5-5",
    "produced_at": NOW, "static_analysis_only": False,
    "inputs": ["git show origin/ju26-issue-2129", "issue #2129 body and maintainer reply (github.com page, fetched 2026-11-14)",
               "receipts/requirements/REQ-2129.yaml", "runs/2129/timemachine.json", "runs/2129/probe/ (executed probes)"],
    **({"prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()} if prompt else {})}
cl_prompt = json.load(open(f"{R}/runs/2283/claims.llm.json"))["prompt"]
pr_prompt = json.load(open(f"{R}/runs/2283/prosecutor.json"))["prompt"]
st_prompt = json.load(open(f"{R}/runs/2283/story.json"))["prompt"]

claims = [
 {"id": "C1", "requirement": "REQ-2129-F1", "source": "requirement", "verifier": "timemachine",
  "text": "A partial class marked [GeneratedMessagePackFormatter] that implements IMessagePackFormatter<T> for a type T from another assembly gets its Serialize and Deserialize members generated in the consuming project.",
  "citations": [cite(G, "var generatedFormatters = context.SyntaxProvider.ForAttributeWithMetadataName("), cite(C, "IsUserDeclaredFormatter = true,"), cite(E, "public void ContractlessClassRoundTrips()")],
  "verifier_notes": "Execution tests build only when the generator writes the bodies (they fail to build on base)."},
 {"id": "C2", "requirement": "REQ-2129-F2", "source": "requirement", "verifier": "timemachine",
  "text": "Without a surrogate, the generated formatter writes every public read-write instance property and field of T as a string-keyed map entry named after the member.",
  "citations": [cite(C, "List<ISymbol> targets = GetInstanceMembers(type).Where(IsPublicReadWrite).OrderBy(m => m.Name, StringComparer.Ordinal).ToList();"), cite(E, "public void ContractlessClassUsesStringKeysForPublicReadWriteMembers()")],
  "verifier_notes": "Probe runs/2129/probe/*.txt compares the wire output with ContractlessStandardResolver."},
 {"id": "C3", "requirement": "REQ-2129-F3", "source": "requirement", "verifier": "argued",
  "text": "Attributes that are present on T are used for the wire contract.",
  "citations": [cite(C, "members = CreateContractlessMembers(type);"), cite(RM, "By default the formatter serializes the type in *contractless* mode")],
  "verifier_notes": "The collector never reads attributes on T; only a surrogate type carries [Key] and [IgnoreMember]. The maintainer's reply asked for the attribute-first behaviour."},
 {"id": "C4", "requirement": "REQ-2129-F4", "source": "requirement", "verifier": "timemachine",
  "text": "The generated resolver registers each generated formatter, so GeneratedMessagePackResolver.Instance returns it for the formatted type.",
  "citations": [cite(C, "ObjectInfos = ImmutableSortedSet.Create(info),"), cite(E, "public void GeneratedFormattersAreRegisteredInGeneratedResolver()")]},
 {"id": "C5", "requirement": "REQ-2129-NF1", "source": "diff", "verifier": "static",
  "text": "The fixture assembly that declares the formatted types has no MessagePack reference, so the feature works without adding anything to the assembly that owns T.",
  "citations": [cite(FX, "This assembly deliberately does NOT reference MessagePack."), cite(E, "public void ContractlessClassNullRoundTrips()")]},
 {"id": "C6", "requirement": "REQ-2129-NF2", "source": "diff", "verifier": "xray",
  "text": "Hand-written formatters and existing generated formatters are unaffected: the exclusion in the formatter search only matches classes carrying the new attribute, and the template keeps 'internal sealed class' for every other formatter.",
  "citations": [cite(U, "&& !symbol.GetAttributes().Any(a => a.AttributeClass?.ToDisplayString() =="), cite(T, "Info.IsUserDeclaredFormatter ? \"partial class\" : \"internal sealed class\"")]},
 {"id": "C7", "requirement": "REQ-2129-NF3", "source": "author-narrative", "verifier": "argued",
  "text": "The new attribute, the four analyzer diagnostics and the surrogate option are documented in the README, in per-diagnostic pages and in the analyzer release notes.",
  "citations": [cite(RM, "### Formatters for types from other assemblies"), cite(AR, "MsgPack019 | Usage | Error | Generated formatter must be partial"), cite(IX, "[MsgPack019](MsgPack019.md) | Generated formatter must be partial")]},
 {"id": "C8", "requirement": "REQ-2129-S1", "source": "diff", "verifier": "argued",
  "text": "Only public read-write members are written. Read-only members and members with a non-public setter are skipped, and no diagnostic says so.",
  "citations": [cite(C, "IFieldSymbol field => field.DeclaredAccessibility == Accessibility.Public && !field.IsReadOnly && !field.IsConst,"), cite(RM, "Read-only members are skipped because they cannot be deserialized."), cite(EP, "public int Doubled => this.Id * 2;")]},
 {"id": "C9", "requirement": "REQ-2129-F1", "source": "diff", "verifier": "timemachine",
  "text": "Misuse of the attribute is reported as a compile error: a non-partial formatter (MsgPack019), a class that does not implement IMessagePackFormatter<T> (MsgPack020), an abstract type (MsgPack021) and surrogate mismatches (MsgPack022, MsgPack005).",
  "citations": [cite(C, "reportDiagnostic?.Invoke(Diagnostic.Create(MsgPack00xMessagePackAnalyzer.GeneratedFormatterMustBePartial, location, formatterName));"), cite(G, "context.RegisterSourceOutput(generatedFormatterDiagnostics, static (context, diagnostic) => context.ReportDiagnostic(diagnostic));"), cite(D, "public async Task FormatterMustBePartial()"), cite(D, "public async Task SurrogateKeysMustNotMixStringAndInt()")]},
 {"id": "C10", "requirement": "REQ-2129-F3", "source": "diff", "verifier": "timemachine",
  "text": "A surrogate type's [Key] and [IgnoreMember] attributes decide which members are written and under which keys, with members matched by name and type.",
  "citations": [cite(C, "ISymbol? target = targetMembers.FirstOrDefault(m => m.Name == surrogateMember.Name);"), cite(E, "public void SurrogateControlsKeysAndMembership()")]},
 {"id": "C11", "requirement": "REQ-2129-NF3", "source": "diff", "verifier": "argued",
  "text": "Adding the public attribute class GeneratedMessagePackFormatterAttribute to the MessagePack.Annotations assembly is additive and does not change existing public API.",
  "citations": [cite(A, "public class GeneratedMessagePackFormatterAttribute : Attribute"), cite(A, "public Type? SurrogateType { get; set; }")]},
]
for c in claims:
    c["evidence_level"] = None; c["status"] = "pending"
json.dump({**meta("claims", cl_prompt), "claims": claims, "uncovered_requirements": [],
  "coverage_gaps": ["The issue's second and third alternatives (user-defined attribute copies, generated attributes) are not implemented and not claimed.",
                    "No claim covers generic types, abstract types, unions or constructor-only types: the README lists them as unsupported and MsgPack021 / NoDeserializingConstructor reject them.",
                    "Only classes and structs with public members were exercised end to end; nested types, base-class members and indexers have no test."]},
          open(f"{R}/runs/2129/claims.json", "w"), indent=2)
# keep an untouched copy for the adjudicator
json.dump(json.load(open(f"{R}/runs/2129/claims.json")), open(f"{R}/runs/2129/claims.llm.json", "w"), indent=2)

story = [
 ("The change answers issue #2129: a project that references MessagePack can declare a partial formatter class marked [GeneratedMessagePackFormatter], and the source generator writes the body for a type from another assembly.", ["C1"]),
 ("By default every public read-write member of the external type is written as a string key, and the seven execution tests pass on head and do not build on base.", ["C1", "C2", "C4"]),
 ("An optional surrogate type with [Key] and [IgnoreMember] attributes sets the keys, and misuse is reported as MsgPack019 to MsgPack022 by six analyzer tests that fail on base and pass on head.", ["C9", "C10"]),
 ("The change ignores attributes that sit on the external type itself, although the maintainer's reply asked for attributes to win when present.", ["C3"]),
 ("Read-only and private-setter members are dropped without a diagnostic, a second formatter for the same type is silently not generated, and the new public attribute lands in the MessagePack.Annotations runtime assembly, so the router reads the whole diff.", ["C8", "C11"]),
]
json.dump({**meta("story", st_prompt), "sentences": [{"text": t, "claims": cs, "text_with_refs": t + " " + "".join(f"[{c}]" for c in cs)} for t, cs in story]},
          open(f"{R}/runs/2129/story.json", "w"), indent=2)

def ref(i, rule, claimids, what, why, q, opts, resolvable, cits):
    return {"id": f"R-2129-{i}", "rule": rule, "claims": claimids, "what": what, "why_ai_cannot_decide": why,
            "question_for_owner": q, "options": opts, "resolvable_by": resolvable, "citations": cits}
refusals = [
 ref(1, "R7-public-api", ["C11"],
     "Whether a new unsealed public attribute with a settable SurrogateType property belongs in the shipped MessagePack.Annotations assembly in this shape.",
     "Public API shape, naming and the choice of a surrogate type are compatibility decisions that outlive this PR. No test can say whether the maintainers want to carry this surface.",
     "Do you accept GeneratedMessagePackFormatterAttribute, as declared, as public API of MessagePack.Annotations?",
     ["Accept as designed", "Require sealed attribute and init-only property", "Require maintainer sign-off first", "Reject"],
     "human only",
     [cite(A, "public class GeneratedMessagePackFormatterAttribute : Attribute"), cite(A, "[AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = false)]")]),
 ref(2, "R1-product-decision", ["C2", "C8"],
     "Whether contractless mode may write every public read-write member of an external type by default.",
     "The probe shows the generated bytes equal the built-in ContractlessStandardResolver, including a member marked [IgnoreDataMember] (Secret). Whether that exposure is acceptable for types the formatter's owner did not write is a data-exposure decision.",
     "Should the default require an opt-in list of members, or is 'all public read-write members' the contract you want to promise?",
     ["Accept contractless default", "Require a surrogate for any type with sensitive members", "Add a diagnostic when [IgnoreDataMember] members are written", "Reject"],
     "partly by evidence: runs/2129/probe/DataMemberAttributes.txt shows the behaviour, the policy stays human",
     [cite(C, "List<ISymbol> targets = GetInstanceMembers(type).Where(IsPublicReadWrite).OrderBy(m => m.Name, StringComparer.Ordinal).ToList();"), cite(RM, "By default the formatter serializes the type in *contractless* mode")]),
 ref(3, "R2-silent-suppression", ["C8"],
     "Whether members that are read-only or have a non-public setter may be dropped from the wire format without any diagnostic.",
     "A dropped member leaves no trace, and the agent's own test locks the omission of Doubled in. The probe confirms Name{get;} and PrivSet{get;private set;} are absent from the output. Whether a round trip that loses data should compile silently is a product decision.",
     "Do you accept silent omission, or must the generator report each skipped public member?",
     ["Accept as documented", "Require an analyzer warning per skipped public member", "Require an opt-in attribute for read-only members", "Reject"],
     "partly by evidence: runs/2129/probe/ReadOnlyAndPrivateSetters.txt; the severity decision is human",
     [cite(C, "IFieldSymbol field => field.DeclaredAccessibility == Accessibility.Public && !field.IsReadOnly && !field.IsConst,"), cite(RM, "Read-only members are skipped because they cannot be deserialized.")]),
 ref(4, "R8-requirement-ambiguity", ["C3"],
     "Whether 'attributes on the type are used if present', from the maintainer's reply on the issue, is part of this requirement.",
     "The reply says attributes win when present, the issue's own motivation is a type that has none, and the agent implemented only the no-attribute path plus a surrogate. Which reading the requirement owner intended is not in the diff.",
     "Is ignoring attributes that sit on T (for example [MessagePackObject] or [DataContract] on an in-assembly type) acceptable for this release?",
     ["Accept, document the limit", "Require attribute-first behaviour", "Reject"],
     "human only",
     [cite(C, "members = CreateContractlessMembers(type);"), cite(C, "members = CreateSurrogateMembers(type, surrogate, referenceSymbols, reportDiagnostic, location, out isIntKey);")]),
 ref(5, "R5-evidence-gap", ["C1", "C4"],
     "Whether a second formatter for the same type, or a formatter for a type that already has [MessagePackObject], may silently get no generated body.",
     "The probe builds two partial formatters for one type and one formatter for a [MessagePackObject] type. In both cases the extra formatter gets no members and the compiler reports CS0535, not a MsgPack diagnostic. No test in the change covers duplicates, so the README's 'nothing else needed' has no evidence behind it for this case.",
     "Should duplicate or conflicting formatter requests produce a MsgPack diagnostic that names the conflict?",
     ["Accept the compiler error", "Require a MsgPack diagnostic", "Require a test for duplicates", "Reject"],
     "partly by evidence: runs/2129/probe/probe-dup.log; the diagnostic policy is human",
     [cite(G, "var generatedFormatters = context.SyntaxProvider.ForAttributeWithMetadataName("), cite(C, "ObjectInfos = ImmutableSortedSet.Create(info),")]),
]
json.dump({**meta("refusals"), "refusals": refusals}, open(f"{R}/runs/2129/refusals.json", "w"), indent=2)

attacks = [
 {"id": "P-2129-1", "claim": "C2", "outcome": "scenario_proposed", "executed": True, "result": "not reproduced",
  "scenario": "The generated formatter diverges from the built-in contractless resolver for attribute-bearing members ([IgnoreDataMember], [DataMember(Name=)]).",
  "test_sketch": "Probe2129Tests.DataMemberAttributes: serialize ProbeDmType with the generated resolver and ContractlessStandardResolver and compare JSON.",
  "result_detail": "Equal output. Both write Secret and ignore the DataMember rename; see runs/2129/probe/DataMemberAttributes.txt.",
  "citations": [cite(C, "List<ISymbol> targets = GetInstanceMembers(type).Where(IsPublicReadWrite).OrderBy(m => m.Name, StringComparer.Ordinal).ToList();")]},
 {"id": "P-2129-2", "claim": "C8", "outcome": "scenario_proposed", "executed": True, "result": "confirmed",
  "scenario": "Public members with no setter or a private setter vanish from the wire format without any diagnostic.",
  "test_sketch": "Probe2129Tests.ReadOnlyAndPrivateSetters with ProbeRoType.",
  "result_detail": "Output is {\"Id\":1}; Name, PrivSet and Internal are absent and the build reports nothing.",
  "citations": [cite(C, "IFieldSymbol field => field.DeclaredAccessibility == Accessibility.Public && !field.IsReadOnly && !field.IsConst,")]},
 {"id": "P-2129-3", "claim": "C4", "outcome": "scenario_proposed", "executed": True, "result": "confirmed",
  "scenario": "Two partial formatters for the same type, or a generated formatter for a [MessagePackObject] type, leave one formatter without a body.",
  "test_sketch": "Probe2129Dup.cs: ProbeDupFormatterA and B for ProbeDupType, and ProbeAttrTypeFormatter for a [MessagePackObject] type.",
  "result_detail": "Build fails with CS0535 on ProbeDupFormatterB and ProbeAttrTypeFormatter; no MsgPack diagnostic names the conflict. See runs/2129/probe/probe-dup.log.",
  "citations": [cite(C, "ObjectInfos = ImmutableSortedSet.Create(info),")]},
 {"id": "P-2129-4", "claim": "C2", "outcome": "scenario_proposed", "executed": True, "result": "not reproduced",
  "scenario": "init-only and required members break deserialization of the generated formatter.",
  "test_sketch": "Probe2129Tests.InitAndRequiredRoundTrip with ProbeInitType.",
  "result_detail": "Round trip passes and wire output equals ContractlessStandardResolver.",
  "citations": [cite(C, "IsInitOnly: isInitOnly,")]},
 {"id": "P-2129-5", "claim": "C6", "outcome": "scenario_proposed", "executed": False, "result": "not executed",
  "scenario": "A hand-written formatter that is also decorated with [GeneratedMessagePackFormatter] by mistake is excluded from the resolver and also fails MsgPack020, hiding the real mistake.",
  "test_sketch": "Roslyn test with the attribute on a class that has a full hand-written body; expect exactly one diagnostic.",
  "citations": [cite(U, "&& !symbol.GetAttributes().Any(a => a.AttributeClass?.ToDisplayString() ==")]},
 {"id": "P-2129-6", "claim": "C7", "outcome": "new_hypothesis", "executed": False, "result": "not executed",
  "scenario": "The README says nothing needs to be added to the library that owns T, but a struct or class that has only a parameterized constructor is rejected with NoDeserializingConstructor, so a common library shape is unsupported.",
  "test_sketch": "Roslyn test: external type with only a ctor taking arguments; expect the existing MsgPack diagnostic at the formatter.",
  "citations": [cite(RM, "- Deserialization uses an accessible parameterless constructor (any struct can be created without one).")]},
]
json.dump({**meta("prosecutor", pr_prompt), "note": "Executed attacks carry result and result_detail; the others are hypotheses only.", "attacks": attacks},
          open(f"{R}/runs/2129/prosecutor.json", "w"), indent=2)

hyps = [
 {"id": "H1", "change": "2129", "rule": "R1-product-decision", "outcome": "REJECTED",
  "what": "The generated contractless formatter writes different bytes than ContractlessStandardResolver for attribute-bearing members.",
  "evidence": ["runs/2129/probe/DataMemberAttributes.txt"], "finding": "Output is equal. Both write a member marked [IgnoreDataMember]; this is shared exposure behaviour, not a divergence. It still goes to the owner as R-2129-2."},
 {"id": "H2", "change": "2129", "rule": "R2-silent-suppression", "outcome": "CONFIRMED",
  "what": "Read-only and private-setter public members are dropped with no diagnostic.",
  "evidence": ["runs/2129/probe/ReadOnlyAndPrivateSetters.txt", "runs/2129/probe/probe-exec.log"], "finding": "Wire output is {\"Id\":1} for ProbeRoType; the built-in contractless output is identical, so this matches existing behaviour but is silent."},
 {"id": "H3", "change": "2129", "rule": "R5-evidence-gap", "outcome": "CONFIRMED",
  "what": "Duplicate formatter requests for one type, or a formatter for a type that already has [MessagePackObject], leave a formatter without a body.",
  "evidence": ["runs/2129/probe/probe-dup.log"], "finding": "CS0535 on ProbeDupFormatterB and ProbeAttrTypeFormatter. No MsgPack diagnostic explains the conflict."},
 {"id": "H4", "change": "2129", "rule": "R1-product-decision", "outcome": "REJECTED",
  "what": "init-only and required members fail to round trip.",
  "evidence": ["runs/2129/probe/InitAndRequired.txt", "runs/2129/probe/probe-exec.log"], "finding": "InitAndRequiredRoundTrip passes; output equals the built-in resolver."},
 {"id": "H5", "change": "2129", "rule": "R4-security-ceiling", "outcome": "CONFIRMED",
  "what": "The router reads the whole 1043-line change because Attributes.cs is in the MessagePack.Annotations runtime area, which has an L3 ceiling.",
  "evidence": ["runs/2129/route.json"], "finding": "The ceiling rule is path-based. The Annotations hunk is a 36-line additive attribute class, while the other 1007 lines sit in the generator, tests and docs. See LESSONS."},
 {"id": "H6", "change": "2129", "rule": "environment", "outcome": "CONFIRMED",
  "what": "The execution tests cannot run under the SDK pinned in global.json.",
  "evidence": ["runs/2129/timemachine/head-exec.log", "runs/2129/timemachine/base-exec.log"], "finding": "SDK 8.0.402 ships Roslyn 4.11 and the generator needs 4.12 (CS9057), on base and head. Under SDK 9.0.321 the same tests run. The pin predates the change."},
]
json.dump({"change": "2129", "generated_at": NOW, "hypotheses": hyps}, open(f"{R}/runs/2129/hypotheses.json", "w"), indent=2)
print("ok", len(claims), "claims;", sum(len(c["citations"]) for c in claims), "citations")
