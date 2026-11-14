// Differential probe for H1 (identical file copied into the base and head worktrees).
// Runs MsgPack00xMessagePackAnalyzer on small apps that use types from a referenced assembly and records
// which diagnostic IDs fire, and whether each has a source location. Compare base vs head output.
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Diagnostics;
using MessagePack.SourceGenerator.Analyzers;

public class DiffProbeTests
{
    private const string Lib = """
using MessagePack;
namespace Lib;
[MessagePackObject] public class UnkeyedClass { [Key(0)] public int A { get; set; } public int B { get; set; } }
[MessagePackObject] public struct UnkeyedStruct { [Key(0)] public int A { get; set; } public int B { get; set; } }
[MessagePackObject] public class UnkeyedGenericClass<T> { [Key(0)] public T A { get; set; } public int B { get; set; } }
[MessagePackObject] public class NoCtor { [Key(0)] public int A { get; set; } private NoCtor() {} public static NoCtor Make() => new NoCtor(); }
[MessagePackObject] public class NoCtorTwoArgs { [Key(0)] public int A { get; set; } public NoCtorTwoArgs(int x, int y) {} }
public class NotMessagePackObject { public int X { get; set; } }
[MessagePackObject] public class MixedKeys { [Key(0)] public int A { get; set; } [Key("b")] public string B { get; set; } }
[MessagePackObject] public class DupKeys { [Key(0)] public int A { get; set; } [Key(0)] public int B { get; set; } }
""";

    private static string Use(string member) =>
        "using MessagePack; using Lib; namespace App; [MessagePackObject] public class Host { [Key(0)] public " + member + " V { get; set; } } [GeneratedMessagePackResolver] partial class R { }";

    public static IEnumerable<object[]> Cases() => new[]
    {
        "S1_source_member_of_non_MPO_metadata_type|NotMessagePackObject",
        "S2_metadata_class_unkeyed|UnkeyedClass",
        "S3_metadata_struct_unkeyed|UnkeyedStruct",
        "S4_metadata_generic_class_unkeyed|UnkeyedGenericClass<int>",
        "S5_metadata_no_deserializing_ctor_private|NoCtor",
        "S6_metadata_ctor_param_mismatch|NoCtorTwoArgs",
        "S7_metadata_mixed_keys|MixedKeys",
        "S8_metadata_dup_keys|DupKeys",
    }.Select(s => new object[] { s.Split('|')[0], s.Split('|')[1] });

    [Theory, MemberData(nameof(Cases))]
    public async Task Probe(string name, string member)
    {
        var fw = await Microsoft.CodeAnalysis.Testing.ReferenceAssemblies.Net.Net80.ResolveAsync(LanguageNames.CSharp, CancellationToken.None);
        var refs = fw.Concat(ReferencesHelper.GetReferences(ReferencesSet.MessagePack)).ToList();
        var opts = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary);
        var parse = CSharpParseOptions.Default.WithLanguageVersion(LanguageVersion.Latest);
        var libC = CSharpCompilation.Create("Lib", new[] { CSharpSyntaxTree.ParseText(Lib, parse) }, refs, opts);
        using var ms = new MemoryStream();
        var emit = libC.Emit(ms);
        Assert.True(emit.Success, string.Join("\n", emit.Diagnostics));
        var libRef = MetadataReference.CreateFromImage(ms.ToArray());
        var app = CSharpCompilation.Create("App", new[] { CSharpSyntaxTree.ParseText(Use(member), parse) }, refs.Append(libRef), opts);
        var withAnalyzers = app.WithAnalyzers(ImmutableArray.Create<DiagnosticAnalyzer>(new MsgPack00xMessagePackAnalyzer()));
        string result;
        try
        {
            var diags = await withAnalyzers.GetAllDiagnosticsAsync();
            result = string.Join(";", diags.Where(d => d.Id.StartsWith("MsgPack") || d.Id == "AD0001").Select(d => d.Id + "@" + (d.Location.IsInSource ? "src" : "none")).OrderBy(x => x));
        }
        catch (Exception e)
        {
            result = "EXCEPTION:" + e.GetType().Name;
        }

        File.AppendAllText(Environment.GetEnvironmentVariable("PROBE_OUT") ?? "/tmp/probe.out", name + "\t" + (result == "" ? "(no diagnostics)" : result) + "\n");
    }
}
