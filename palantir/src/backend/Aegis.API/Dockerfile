FROM mcr.microsoft.com/dotnet/sdk:10.0-preview AS build
WORKDIR /src

COPY Aegis.Domain/Aegis.Domain.csproj Aegis.Domain/
COPY Aegis.Application/Aegis.Application.csproj Aegis.Application/
COPY Aegis.Infrastructure/Aegis.Infrastructure.csproj Aegis.Infrastructure/
COPY Aegis.API/Aegis.API.csproj Aegis.API/
RUN dotnet restore Aegis.API/Aegis.API.csproj

COPY . .
RUN dotnet publish Aegis.API/Aegis.API.csproj -c Release -o /app/publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0-preview AS runtime
WORKDIR /app
COPY --from=build /app/publish .

ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Development

EXPOSE 8080
ENTRYPOINT ["dotnet", "Aegis.API.dll"]
