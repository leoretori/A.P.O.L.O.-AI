// A.P.O.L.O. Assistant — extensão VS Code
// Conecta ao servidor A.P.O.L.O. via API para chat, revisão e contexto de arquivo.

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

// ── Provedor do webview da sidebar ────────────────────────────────────────────

class ApoloChatViewProvider {
    constructor(context) {
        this._context = context;
        this._view = null;
    }

    resolveWebviewView(webviewView) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this._context.extensionUri, 'media'),
            ],
        };

        webviewView.webview.html = this._buildHtml(webviewView.webview);

        // Mensagens vindas do webview
        webviewView.webview.onDidReceiveMessage(msg => {
            switch (msg.type) {
                case 'openExternal':
                    vscode.env.openExternal(vscode.Uri.parse(msg.url));
                    break;
                case 'copyCode':
                    vscode.env.clipboard.writeText(msg.text);
                    vscode.window.showInformationMessage('Código copiado!');
                    break;
                case 'insertCode':
                    this._insertCode(msg.text);
                    break;
                case 'ready':
                    this._sendConfig();
                    break;
            }
        });

        // Repassa config quando o webview fica visível
        webviewView.onDidChangeVisibility(() => {
            if (webviewView.visible) this._sendConfig();
        });
    }

    // ── Mensagens para o webview ──────────────────────────────────────────────

    _sendConfig() {
        if (!this._view) return;
        const cfg = vscode.workspace.getConfiguration('apolo');
        this._view.webview.postMessage({
            type: 'config',
            serverUrl: cfg.get('serverUrl', 'http://192.168.15.17:8000'),
            smart: cfg.get('smartMode', false),
        });
    }

    _post(msg) {
        if (!this._view) return;
        this._view.webview.postMessage(msg);
        this._view.show(true); // foca a sidebar
    }

    // ── Ações disparadas pelos comandos ──────────────────────────────────────

    askAboutFile(editor, question) {
        const doc = editor.document;
        const fileName = path.basename(doc.fileName);
        const lang = doc.languageId;
        const maxLines = vscode.workspace.getConfiguration('apolo').get('maxFileLines', 300);
        const lines = doc.getText().split('\n').slice(0, maxLines);
        const content = lines.join('\n');
        const truncated = doc.lineCount > maxLines
            ? `\n\n*(arquivo truncado — exibindo ${maxLines}/${doc.lineCount} linhas)*` : '';

        const fullMsg = `${question || `Explique o arquivo \`${fileName}\``}\n\n` +
            `**Arquivo:** \`${fileName}\`\n\`\`\`${lang}\n${content}\n\`\`\`${truncated}`;

        this._post({ type: 'sendMessage', content: fullMsg });
    }

    reviewSelection(editor) {
        const sel = editor.selection;
        if (sel.isEmpty) {
            vscode.window.showWarningMessage('A.P.O.L.O.: selecione código para revisar.');
            return;
        }
        const code = editor.document.getText(sel);
        const lang = editor.document.languageId;
        this._post({ type: 'reviewCode', code, lang });
    }

    explainSelection(editor) {
        const sel = editor.selection;
        if (sel.isEmpty) {
            vscode.window.showWarningMessage('A.P.O.L.O.: selecione código para explicar.');
            return;
        }
        const code = editor.document.getText(sel);
        const lang = editor.document.languageId;
        const msg = `Explique este código em português:\n\n\`\`\`${lang}\n${code}\n\`\`\``;
        this._post({ type: 'sendMessage', content: msg });
    }

    // ── Inserir código na posição do cursor ──────────────────────────────────

    _insertCode(text) {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;
        editor.edit(eb => {
            const pos = editor.selection.active;
            eb.insert(pos, text);
        });
    }

    // ── HTML do webview ──────────────────────────────────────────────────────

    _buildHtml(webview) {
        const htmlPath = vscode.Uri.joinPath(this._context.extensionUri, 'media', 'sidebar.html');
        let html = fs.readFileSync(htmlPath.fsPath, 'utf-8');
        // Substitui caminhos de recurso local para URIs do webview
        const mediaUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this._context.extensionUri, 'media')
        );
        html = html.replace(/\$\{mediaUri\}/g, mediaUri.toString());
        return html;
    }
}


// ── Ativação da extensão ──────────────────────────────────────────────────────

function activate(context) {
    const provider = new ApoloChatViewProvider(context);

    // Registra o provedor da sidebar
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('apolo.chatView', provider, {
            webviewOptions: { retainContextWhenHidden: true },
        })
    );

    // Comando: perguntar sobre o arquivo aberto (Ctrl+Shift+A)
    context.subscriptions.push(
        vscode.commands.registerCommand('apolo.askAboutFile', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('A.P.O.L.O.: nenhum arquivo aberto.');
                return;
            }
            const fileName = path.basename(editor.document.fileName);
            const question = await vscode.window.showInputBox({
                prompt: `A.P.O.L.O. — sobre "${fileName}"`,
                placeHolder: 'Ex.: Explique este código, O que este arquivo faz?, Quais bugs tem?',
                value: '',
            });
            if (question === undefined) return; // cancelado
            provider.askAboutFile(editor, question.trim() || undefined);
        })
    );

    // Comando: revisar código selecionado (Ctrl+Shift+R)
    context.subscriptions.push(
        vscode.commands.registerCommand('apolo.reviewSelection', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) provider.reviewSelection(editor);
        })
    );

    // Comando: explicar código selecionado
    context.subscriptions.push(
        vscode.commands.registerCommand('apolo.explainSelection', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) provider.explainSelection(editor);
        })
    );

    // Comando: abrir/focar o chat
    context.subscriptions.push(
        vscode.commands.registerCommand('apolo.openChat', () => {
            vscode.commands.executeCommand('apolo.chatView.focus');
        })
    );

    // Detecta mudança de configuração e repassa ao webview
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('apolo')) provider._sendConfig();
        })
    );
}

function deactivate() {}

module.exports = { activate, deactivate };
