; Instalador de Descargador Bombastic (Inno Setup 6).
; Lo compila build/build.ps1: ISCC.exe /DAppVersion=x.y.z build\installer.iss
; Necesita out\dist\DescargadorBombastic (PyInstaller), out\bin (yt-dlp y ffmpeg) y
; out\registry.iss (python build\gen_installer_registry.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Descargador Bombastic"
#define AppExe "DescargadorBombastic.exe"

[Setup]
AppId={{6C1E8F0A-3B7D-4F52-9E0B-5B0D1C2A7E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Por usuario por defecto (sin administrador), con opción para todos los usuarios.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\out\installer
OutputBaseFilename=DescargadorBombastic-Setup-{#AppVersion}
SetupIconFile=..\bombastic\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\THIRD_PARTY_LICENSES.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
spanish.TaskContextMenu=Añadir "Descargador Bombastic" al menú contextual de vídeos y audios
english.TaskContextMenu=Add "Descargador Bombastic" to the context menu of videos and audio
spanish.TaskStartup=Iniciar con Windows (minimizado en la bandeja)
english.TaskStartup=Start with Windows (minimized to the tray)
spanish.CtxMenu=Descargador Bombastic
english.CtxMenu=Descargador Bombastic
spanish.CtxEdit=Editar en Descargador Bombastic
english.CtxEdit=Edit in Descargador Bombastic
spanish.CtxConvert=Convertir a MP4
english.CtxConvert=Convert to MP4
spanish.CtxMp3=Extraer audio MP3
english.CtxMp3=Extract MP3 audio
spanish.CtxCompress=Comprimir…
english.CtxCompress=Compress…
spanish.CtxRecipe=Receta: {name}
english.CtxRecipe=Recipe: {name}
spanish.DeleteData=¿Borrar también tus datos (historial, perfiles, recetas, ajustes y la carpeta bin)? Los archivos descargados no se tocan.
english.DeleteData=Also delete your data (history, profiles, recipes, settings and the bin folder)? Downloaded files are not touched.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "contextmenu"; Description: "{cm:TaskContextMenu}"
Name: "startup"; Description: "{cm:TaskStartup}"; Flags: unchecked

[Files]
Source: "..\out\dist\DescargadorBombastic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; La app los copia a la carpeta de datos en el primer arranque (actualizables sin administrador).
Source: "..\out\bin\*.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "..\out\bin\SOURCES.txt"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "..\THIRD_PARTY_LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\manual_usuario.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DescargadorBombastic"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: startup
#include "..\out\registry.iss"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Actualización desde la propia app (/relaunch=1): se vuelve a abrir al terminar.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: ShouldRelaunch

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:relaunch|0}') = '1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\DescargadorBombastic'), True, True, True);
end;
