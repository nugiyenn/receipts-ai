#!/bin/zsh
export DOTNET_ROOT=$HOME/.dotnet PATH=$HOME/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1
R=/Users/andy/Downloads/Junction2
T=$R/receipts/runs/2129/timemachine
mkdir -p $T
DIAG='FullyQualifiedName~GeneratedMessagePackFormatterTests'
t0=$(date +%s)
cd $R/wt/2129-head && dotnet test tests/MessagePack.SourceGenerator.Tests -f net8.0 --filter "$DIAG" --logger 'console;verbosity=normal' > $T/head-diag.log 2>&1
echo "head-diag secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
t0=$(date +%s)
cd $R/wt/2129-head && dotnet test tests/MessagePack.SourceGenerator.ExecutionTests -f net8.0 --filter 'FullyQualifiedName~GeneratedFormatterForExternalTypesTests' --logger 'console;verbosity=normal' > $T/head-exec.log 2>&1
echo "head-exec secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
# base: copy head's new test files into base, run same filters
t0=$(date +%s)
cp $R/wt/2129-head/tests/MessagePack.SourceGenerator.Tests/GeneratedMessagePackFormatterTests.cs $R/wt/2129-base/tests/MessagePack.SourceGenerator.Tests/
cd $R/wt/2129-base && dotnet test tests/MessagePack.SourceGenerator.Tests -f net8.0 --filter "$DIAG" --logger 'console;verbosity=normal' > $T/base-diag.log 2>&1
echo "base-diag secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
t0=$(date +%s)
mkdir -p $R/wt/2129-base/tests/MessagePack.SourceGenerator.ExecutionTests
cp $R/wt/2129-head/tests/MessagePack.SourceGenerator.ExecutionTests/GeneratedFormatterForExternalTypes*.cs $R/wt/2129-base/tests/MessagePack.SourceGenerator.ExecutionTests/
cp -R $R/wt/2129-head/tests/MessagePack.SourceGenerator.ExternalTypes $R/wt/2129-base/tests/
cp $R/wt/2129-head/tests/MessagePack.SourceGenerator.ExecutionTests/MessagePack.SourceGenerator.ExecutionTests.csproj $R/wt/2129-base/tests/MessagePack.SourceGenerator.ExecutionTests/
cd $R/wt/2129-base && dotnet test tests/MessagePack.SourceGenerator.ExecutionTests -f net8.0 --filter 'FullyQualifiedName~GeneratedFormatterForExternalTypesTests' --logger 'console;verbosity=normal' > $T/base-exec.log 2>&1
echo "base-exec secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
echo done >> $T/timings.txt
