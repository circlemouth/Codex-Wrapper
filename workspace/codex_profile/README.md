# Codex プロファイル上書きディレクトリ

- `codex_agents.sample.md` と `codex_config.sample.toml` はサンプルです。
- 実際に適用したい内容は `codex_agents.md`、`codex_config.toml` としてこのディレクトリに配置してください。
- サーバー起動時にこれらのファイルが存在する場合のみ、Codex のホームディレクトリにある `AGENTS.md` と `config.toml` を上書きします。
- 片方だけ配置した場合は、存在するファイルのみがコピーされます。
- 互換性のために旧名称 (`agent.md` / `config.toml`) も読み込みますが、起動時に警告が表示されるので新名称への移行を推奨します。

カスタムファイルをコミットしないために `.gitignore` で `codex_agents.md` / `codex_config.toml`（および旧名称）を除外しています。
