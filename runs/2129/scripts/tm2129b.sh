#!/bin/zsh
export DOTNET_ROOT=$HOME/.dotnet PATH=$HOME/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1
R=/Users/andy/Downloads/Junction2
T=$R/receipts/runs/2129/timemachine
F='FullyQualifiedName~GeneratedFormatterForExternalTypesTests'
t0=$(date +%s)
cd $R/wt/2129-head && dotnet --version > $T/sdk9-version.txt 2>&1
dotnet test tests/MessagePack.SourceGenerator.ExecutionTests -f net8.0 --filter "$F" --logger 'console;verbosity=normal' > $T/head-exec-sdk9.log 2>&1
echo "head-exec-sdk9 secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
t0=$(date +%s)
cd $R/wt/2129-base && dotnet test tests/MessagePack.SourceGenerator.ExecutionTests -f net8.0 --filter "$F" --logger 'console;verbosity=normal' > $T/base-exec-sdk9.log 2>&1
echo "base-exec-sdk9 secs $(( $(date +%s)-t0 ))" >> $T/timings.txt
echo done2 >> $T/timings.txt
