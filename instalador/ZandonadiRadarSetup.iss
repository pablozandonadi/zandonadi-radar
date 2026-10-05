; Script do Inno Setup pro instalador do Zandonadi Radar.
; Gera um instalador clássico do Windows (tela de boas-vindas, escolha de
; pasta, checkbox "criar ícone na área de trabalho", barra de progresso,
; tela final com "abrir o programa agora") a partir do build já feito pelo
; PyInstaller (pasta dist\ZandonadiRadar, com o .exe e tudo que ele precisa
; pra rodar sem precisar de Python instalado).
;
; Não compile na mão: use instalador\gerar_instalador.ps1, que passa
; SourceDistDir/OutputDir (pastas temporárias fora do Google Drive).
;
; Instala numa pasta por usuário (AppData\Local\Programs), não em
; "Arquivos de Programas" — o programa precisa gravar o banco de dados
; (precos.db) e o log de rotinas do lado do .exe, o que exigiria
; administrador se fosse instalado em Arquivos de Programas. Assim, não
; precisa de permissão de administrador pra instalar nem pra rodar.

#define MyAppName "Zandonadi Radar"
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif
#define MyAppPublisher "Zandonadi"
#define MyAppExeName "ZandonadiRadar.exe"
#ifndef SourceDistDir
  #define SourceDistDir "dist\ZandonadiRadar"
#endif
#ifndef OutputDir
  #define OutputDir "output"
#endif
#define ProjDir ".."

[Setup]
AppId={{8F2C1A6E-4B3D-4E7A-9C5F-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=ZandonadiRadarSetup
SetupIconFile={#ProjDir}\icone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um ícone na área de trabalho"; GroupDescription: "Ícones adicionais:"

; Atualizando uma instalação da versão antiga (Tkinter): a pasta _internal de
; lá tinha o matplotlib/Tkinter etc., que a versão nova não usa — apaga antes
; de copiar os arquivos novos. precos.db, llm_config.py e email_config.py
; ficam na pasta principal (não em _internal), então ficam intactos.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjDir}\guia_configuracao.pdf"; DestDir: "{app}"; Flags: ignoreversion
; Instalador "limpo" de propósito — sem precos.db, sem llm_config.py, sem
; email_config.py. Isso aqui é pra qualquer pessoa instalar, não só pra
; quem já usa o programa; ninguém deveria abrir o app e ver os produtos de
; outra pessoa. (Se você quiser levar o SEU banco de dados pra outro PC
; seu, é só copiar o arquivo precos.db manualmente pra pasta instalada.)

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Guia de configuração (PDF)"; Filename: "{app}\guia_configuracao.pdf"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[Code]
var
  ConfigPage: TInputQueryWizardPage;

{ Escreve o valor como string literal Python (aspas simples), escapando
  barra invertida e aspas simples — pra não quebrar o .py gerado se a
  chave/senha tiver algum desses caracteres. }
function PyEscape(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '''', '\''', True);
  Result := '''' + S + '''';
end;

function TestarChaveOpenAI(Chave: String): Boolean;
var
  Http: Variant;
begin
  Result := False;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('GET', 'https://api.openai.com/v1/models', False);
    Http.SetRequestHeader('Authorization', 'Bearer ' + Chave);
    Http.SetTimeouts(5000, 5000, 8000, 8000);
    Http.Send('');
    Result := Http.Status = 200;
  except
    Result := False;
  end;
end;

{ Manda um e-mail de teste de verdade (pra própria conta) via CDO — é a
  forma mais simples de validar e-mail + senha de app do Gmail sem precisar
  reimplementar SMTP na mão. Usa porta 465/SSL implícito (mais confiável no
  CDO do que STARTTLS na 587) só pra ESSE teste; o app em si usa 587 com
  STARTTLS normalmente (ver notificacoes.py), o que já foi testado antes. }
function TestarEmailGmail(Email, SenhaApp: String): Boolean;
var
  Msg: Variant;
begin
  Result := False;
  try
    Msg := CreateOleObject('CDO.Message');
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/sendusing'] := 2;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/smtpserver'] := 'smtp.gmail.com';
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/smtpserverport'] := 465;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/smtpusessl'] := True;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/smtpauthenticate'] := 1;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/sendusername'] := Email;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/sendpassword'] := SenhaApp;
    Msg.Configuration.Fields.Item['http://schemas.microsoft.com/cdo/configuration/smtpconnectiontimeout'] := 15;
    Msg.Configuration.Fields.Update;

    // "To" e palavra reservada no Pascal Script (do for..to..) - Msg.To
    // direto nao compila, entao os cabecalhos vao pela colecao de campos
    // do CDO (schema de mailheader) em vez da propriedade de atalho.
    Msg.Fields.Item['urn:schemas:mailheader:to'] := Email;
    Msg.Fields.Item['urn:schemas:mailheader:from'] := Email;
    Msg.Fields.Item['urn:schemas:mailheader:subject'] := 'Zandonadi Radar - configuracao concluida';
    Msg.Fields.Update;
    Msg.TextBody := 'Se voce recebeu este e-mail, o envio de alertas de preco do Zandonadi Radar esta funcionando.';
    Msg.Send;
    Result := True;
  except
    Result := False;
  end;
end;

{ Lê "NomeVar = 'valor'" (ou com aspas duplas) de dentro do texto de um
  llm_config.py/email_config.py já existente — usado pra pré-preencher a
  página com a configuração atual numa REINSTALAÇÃO (atualização), pra não
  perder a chave/senha já configuradas se a pessoa só clicar "Avançar" sem
  mexer nos campos. }
function ExtrairValorPython(Conteudo, NomeVar: String): String;
var
  Idx, IdxValorInicio, IdxAspaFechaRelativo: Integer;
  AspaChar, Resto: String;
begin
  Result := '';
  Idx := Pos(NomeVar + ' = ', Conteudo);
  if Idx = 0 then
    Exit;
  IdxValorInicio := Idx + Length(NomeVar + ' = ');
  if IdxValorInicio > Length(Conteudo) then
    Exit;
  AspaChar := Copy(Conteudo, IdxValorInicio, 1);
  if (AspaChar <> '''') and (AspaChar <> '"') then
    Exit;
  IdxValorInicio := IdxValorInicio + 1;
  { Pascal Script desta versão não tem PosEx — acha a aspa de fechamento
    procurando só no restante do texto a partir daqui. }
  Resto := Copy(Conteudo, IdxValorInicio, Length(Conteudo) - IdxValorInicio + 1);
  IdxAspaFechaRelativo := Pos(AspaChar, Resto);
  if IdxAspaFechaRelativo = 0 then
    Exit;
  Result := Copy(Resto, 1, IdxAspaFechaRelativo - 1);
  { desfaz o escape que o PyEscape (lá embaixo) fez ao gravar o arquivo }
  StringChangeEx(Result, '\''', '''', True);
  StringChangeEx(Result, '\\', '\', True);
end;

// O app novo desenha a interface num componente da Microsoft (WebView2).
// Windows 11 e Windows 10 atualizado ja trazem; se nao tiver, baixa o
// instalador oficial (bootstrapper, ~2 MB) e instala em silencio.
function WebView2Instalado: Boolean;
var
  Versao: String;
begin
  Versao := '';
  if not RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Versao) then
    if not RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Versao) then
      RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Versao);
  Result := (Versao <> '') and (Versao <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  CodigoSaida: Integer;
begin
  Result := '';
  if WebView2Instalado then
    Exit;
  try
    WizardForm.StatusLabel.Caption := 'Baixando o componente WebView2 da Microsoft...';
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703', 'MicrosoftEdgeWebview2Setup.exe', '', nil);
    WizardForm.StatusLabel.Caption := 'Instalando o componente WebView2...';
    Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, CodigoSaida);
  except
    // sem internet ou bloqueado: segue assim mesmo, o aviso vem logo abaixo
  end;
  if not WebView2Instalado then
    MsgBox('Nao consegui instalar o componente WebView2 da Microsoft, que o Zandonadi Radar usa pra desenhar a tela. ' +
           'Se o programa nao abrir, instale-o manualmente (procure por "WebView2 Runtime" no site da Microsoft) e abra o programa de novo.',
           mbInformation, MB_OK);
end;

var
  ConfigJaPreenchida: Boolean;
  BotaoGuia: TNewButton;

procedure AbrirGuiaPDF(Sender: TObject);
var
  ErrorCode: Integer;
begin
  { O PDF já foi copiado pro diretório temporário do instalador (ver a
    chamada ExtractTemporaryFile em InitializeWizard) antes da página aparecer. }
  ShellExec('open', ExpandConstant('{tmp}\guia_configuracao.pdf'), '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure InitializeWizard;
begin
  // Extrai o PDF pra pasta temporaria do instalador ja de cara, pra o botao
  // "Ver guia" funcionar mesmo antes dos arquivos serem copiados pra pasta
  // de instalacao de verdade (isso so acontece depois, ja instalando).
  ExtractTemporaryFile('guia_configuracao.pdf');

  ConfigPage := CreateInputQueryPage(wpSelectDir,
    'Chave da OpenAI e e-mail de alertas',
    'Opcional — dá pra pular e configurar depois',
    'A chave da OpenAI melhora a busca (filtra resultados e lê preço quando o site muda). ' +
    'O e-mail do Gmail é pra onde as Rotinas avisam quando um preço cai. ' +
    'Pode deixar os campos em branco e configurar depois, dentro da pasta onde o programa for instalado.' + #13#10 +
    'A senha do Gmail precisa ser uma "senha de app" de 16 letras (myaccount.google.com/apppasswords) — não é a senha normal da conta.' + #13#10 +
    'Atualizando uma instalação já existente? Os campos já vêm preenchidos com o que você configurou antes.');
  ConfigPage.Add('Chave da API da OpenAI (sk-...):', False);
  ConfigPage.Add('E-mail do Gmail que vai enviar os alertas:', False);
  ConfigPage.Add('Senha de app do Gmail (16 caracteres):', True);

  BotaoGuia := TNewButton.Create(WizardForm);
  BotaoGuia.Parent := ConfigPage.Surface;
  BotaoGuia.Caption := '📄 Ver guia passo a passo (PDF)';
  BotaoGuia.Width := ScaleX(220);
  BotaoGuia.Height := ScaleY(23);
  BotaoGuia.Left := 0;
  BotaoGuia.Top := ConfigPage.Edits[2].Top + ConfigPage.Edits[2].Height + ScaleY(16);
  BotaoGuia.OnClick := @AbrirGuiaPDF;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  ConteudoLLM, ConteudoEmail: AnsiString;
begin
  if (CurPageID <> ConfigPage.ID) or ConfigJaPreenchida then
    Exit;
  ConfigJaPreenchida := True;

  { LoadStringFromFile só trabalha com AnsiString nesta versão do Inno Setup. }
  if LoadStringFromFile(ExpandConstant('{app}\llm_config.py'), ConteudoLLM) then
    ConfigPage.Values[0] := ExtrairValorPython(String(ConteudoLLM), 'OPENAI_API_KEY');

  if LoadStringFromFile(ExpandConstant('{app}\email_config.py'), ConteudoEmail) then
  begin
    ConfigPage.Values[1] := ExtrairValorPython(String(ConteudoEmail), 'SMTP_EMAIL');
    ConfigPage.Values[2] := ExtrairValorPython(String(ConteudoEmail), 'SMTP_SENHA_APP');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ApiKey, GmailEmail, GmailSenha: String;
begin
  Result := True;
  if CurPageID <> ConfigPage.ID then
    Exit;

  ApiKey := Trim(ConfigPage.Values[0]);
  GmailEmail := Trim(ConfigPage.Values[1]);
  GmailSenha := Trim(ConfigPage.Values[2]);

  if (GmailEmail <> '') <> (GmailSenha <> '') then
  begin
    MsgBox('Preencha o e-mail E a senha de app do Gmail, ou deixe os dois em branco.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if ApiKey <> '' then
  begin
    WizardForm.NextButton.Enabled := False;
    Try
      if TestarChaveOpenAI(ApiKey) then
        MsgBox('Chave da OpenAI validada com sucesso!', mbInformation, MB_OK)
      else if MsgBox('Não consegui validar essa chave agora com a OpenAI (chave errada, sem internet, ou sem cota). ' +
                      'Quer continuar mesmo assim e revisar depois?', mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        Exit;
      end;
    Finally
      WizardForm.NextButton.Enabled := True;
    End;
  end;

  if GmailEmail <> '' then
  begin
    WizardForm.NextButton.Enabled := False;
    Try
      if TestarEmailGmail(GmailEmail, GmailSenha) then
        MsgBox('E-mail de teste enviado com sucesso! Confira sua caixa de entrada.', mbInformation, MB_OK)
      else if MsgBox('Não consegui enviar um e-mail de teste com esses dados (confira se é senha de APP, não a senha normal da conta). ' +
                      'Quer continuar mesmo assim e revisar depois?', mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        Exit;
      end;
    Finally
      WizardForm.NextButton.Enabled := True;
    End;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ApiKey, GmailEmail, GmailSenha, LLMAtivado: String;
  LLMContent, EmailContent: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  ApiKey := Trim(ConfigPage.Values[0]);
  GmailEmail := Trim(ConfigPage.Values[1]);
  GmailSenha := Trim(ConfigPage.Values[2]);

  if ApiKey <> '' then
    LLMAtivado := 'True'
  else
    LLMAtivado := 'False';

  { SaveStringToFile grava em ANSI, nao UTF-8 (SaveStringToUTF8File nao
    existe nesta versao do Inno Setup) — por isso o conteudo abaixo e todo
    ASCII puro de proposito (sem acento), pra nao gerar byte invalido pro
    "# -*- coding: utf-8 -*-" declarado no topo do .py. }
  LLMContent :=
    '# -*- coding: utf-8 -*-' + #13#10 +
    '# Gerado pelo instalador do Zandonadi Radar - edite livremente.' + #13#10 +
    'OPENAI_API_KEY = ' + PyEscape(ApiKey) + #13#10 +
    'OPENAI_MODELO = "gpt-4o-mini"' + #13#10 +
    'LLM_ATIVADO = ' + LLMAtivado + #13#10;
  SaveStringToFile(ExpandConstant('{app}\llm_config.py'), LLMContent, False);

  EmailContent :=
    '# -*- coding: utf-8 -*-' + #13#10 +
    '# Gerado pelo instalador do Zandonadi Radar - edite livremente.' + #13#10 +
    'SMTP_HOST = "smtp.gmail.com"' + #13#10 +
    'SMTP_PORT = 587' + #13#10 +
    'SMTP_EMAIL = ' + PyEscape(GmailEmail) + #13#10 +
    'SMTP_SENHA_APP = ' + PyEscape(GmailSenha) + #13#10;
  SaveStringToFile(ExpandConstant('{app}\email_config.py'), EmailContent, False);
end;
