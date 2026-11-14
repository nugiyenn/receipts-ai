// Executes Gemini prosecutor hypotheses P-C10 (record primary-ctor property w/ null key) and controls.
// Same file is copied into base and head worktrees; output compared.
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Diagnostics;
using MessagePack.SourceGenerator.Analyzers;

public class GemProbeTests
{
    public static IEnumerable<object[]> Cases() => new[]
    {
        "G1_class_property_null_key|[MessagePackObject] public class Host { [Key((string)null)] public int V { get; set; } }",
        "G2_positional_record_null_key|[MessagePackObject] public record Host([property: Key((string)null)] int V);",
        "G3_positional_record_valid_key_control|[MessagePackObject] public record Host([property: Key(0)] int V);",
        "G4_positional_record_unkeyed_member|[MessagePackObject] public record Host([property: Key(0)] int A, int B);",
        "G5_record_body_property_null_key|[MessagePackObject] public record Host { [Key((string)null)] public int V { get; init; } }",
    }.Select(s => new object[] { s.Split('|')[0], s.Split('|')[1] });

    [Theory, MemberData(nameof(Cases))]
    public async Task Probe(string name, string decl)
    {
        var fw = await Microsoft.CodeAnalysis.Testing.ReferenceAssemblies.Net.Net80.ResolveAsync(LanguageNames.CSharp, CancellationToken.None);
        var refs = fw.Concat(ReferencesHelper.GetReferences(ReferencesSet.MessagePack)).ToList();
        var parse = CSharpParseOptions.Default.WithLanguageVersion(LanguageVersion.Latest);
        var src = "#nullable disable\nusing MessagePack; namespace App; " + decl + " [GeneratedMessagePackResolver] partial class R { }";
        var app = CSharpCompilation.Create("App", new[] { CSharpSyntaxTree.ParseText(src, parse) }, refs, new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
        var withAnalyzers = app.WithAnalyzers(ImmutableArray.Create<DiagnosticAnalyzer>(new MsgPack00xMessagePackAnalyzer()));
        string result;
        try
        {
            var diags = await withAnalyzers.GetAllDiagnosticsAsync();
            result = string.Join(";", diags.Where(d => d.Id.StartsWith("MsgPack") || d.Id == "AD0001" || d.Id.StartsWith("CS8")).Select(d => d.Id + "@" + (d.Location.IsInSource ? "src" : "none") + (d.Id == "AD0001" ? ":" + d.GetMessage().Substring(0, Math.Min(140, d.GetMessage().Length)).Replace('\n', ' ') : "")).OrderBy(x => x));
        }
        catch (Exception e)
        {
            result = "EXCEPTION:" + e.GetType().Name;
        }
        File.AppendAllText(Environment.GetEnvironmentVariable("PROBE_OUT") ?? "/tmp/gemprobe.out", name + "\t" + (result == "" ? "(no diagnostics)" : result) + "\n");
    }
}
