# A.P.O.L.O. Assistant — Extensão VS Code

Conecta o VS Code ao seu servidor A.P.O.L.O. local para chat, revisão de código e contexto de arquivo — sem sair do editor.

## Funcionalidades

| Recurso | Como usar |
|---|---|
| **Chat na sidebar** | Ícone ☀️ na barra de atividades |
| **Perguntar sobre arquivo** | `Ctrl+Shift+A` com um arquivo aberto |
| **Revisar código** | Selecione → `Ctrl+Shift+R` (ou clique direito) |
| **Explicar seleção** | Selecione → clique direito → *Explicar* |
| **Inserir código** | Botão "Inserir" em qualquer bloco de código da resposta |
| **Copiar código** | Botão "Copiar" em qualquer bloco de código |

## Instalação (modo desenvolvimento)

**Pré-requisito:** o servidor A.P.O.L.O. rodando em `http://192.168.15.17:8000`

```bash
# 1. Abra a pasta da extensão no VS Code
code C:\Users\leore\Documents\Apolo_AI\apolo-vscode

# 2. Pressione F5 — abre uma janela "Extension Development Host"
#    com a extensão carregada
```

Para instalar permanentemente (sem precisar do F5 toda vez):

```bash
# Instale o vsce (empacotador de extensões)
npm install -g @vscode/vsce

# Empacote a extensão
cd apolo-vscode
vsce package

# Instale o .vsix gerado
code --install-extension apolo-assistant-0.1.0.vsix
```

## Configurações

| Chave | Padrão | Descrição |
|---|---|---|
| `apolo.serverUrl` | `http://192.168.15.17:8000` | URL do servidor |
| `apolo.smartMode` | `false` | Usar modelo 14b por padrão |
| `apolo.maxFileLines` | `300` | Máximo de linhas ao enviar arquivo como contexto |

Para mudar: `Ctrl+,` → buscar "A.P.O.L.O."

## Atalhos

| Atalho | Ação |
|---|---|
| `Ctrl+Shift+A` | Perguntar sobre o arquivo aberto |
| `Ctrl+Shift+R` | Revisar código selecionado |
| `Ctrl+,` → apolo | Configurações da extensão |
