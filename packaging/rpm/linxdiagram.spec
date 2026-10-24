Name:           linxdiagram
Version:        1.0.0
Release:        1%{?dist}
Summary:        Éditeur de diagrammes natif compatible Visio
License:        MIT
URL:            https://github.com/Joss943/LinXdiagram
BuildArch:      noarch
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3 >= 3.11
BuildRequires:  desktop-file-utils
Requires:       python3 >= 3.11
Requires:       python3-pyqt6
Requires:       qt6-qtsvg
Requires:       openssl-libs
Recommends:     carlito-fonts

%description
LinXdiagram est un éditeur de diagrammes natif pour Linux, pensé pour les habitués
de Microsoft Visio : ruban, gabarits de formes, connecteurs dynamiques, connexion
automatique, repères d'alignement, import et export au format .vsdx.
Sécurisé par conception : aucune macro, aucune connexion réseau, fichiers
strictement validés, chiffrement AES-256-GCM des documents par mot de passe.

%prep
%autosetup

%build
# Rien à compiler : application Python.

%install
mkdir -p %{buildroot}%{_datadir}/%{name} %{buildroot}%{_bindir}
cp -R linxdiagram %{buildroot}%{_datadir}/%{name}/
find %{buildroot}%{_datadir}/%{name} -name '__pycache__' -type d -prune -exec rm -rf {} +
sed "s|@LIBDIR@|%{_datadir}/%{name}|; s|@PYFLAGS@|-I|" bin/linxdiagram > %{buildroot}%{_bindir}/linxdiagram
chmod 755 %{buildroot}%{_bindir}/linxdiagram
install -Dm644 packaging/io.github.joss943.LinXdiagram.desktop \
    %{buildroot}%{_datadir}/applications/io.github.joss943.LinXdiagram.desktop
install -Dm644 packaging/io.github.joss943.LinXdiagram.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.joss943.LinXdiagram.svg
install -Dm644 packaging/io.github.joss943.LinXdiagram-mime.xml \
    %{buildroot}%{_datadir}/mime/packages/io.github.joss943.LinXdiagram.xml
install -Dm644 packaging/io.github.joss943.LinXdiagram.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.joss943.LinXdiagram.metainfo.xml
%{python3} -m compileall -q -d %{_datadir}/%{name} %{buildroot}%{_datadir}/%{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.joss943.LinXdiagram.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/linxdiagram
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.joss943.LinXdiagram.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.joss943.LinXdiagram.svg
%{_datadir}/mime/packages/io.github.joss943.LinXdiagram.xml
%{_metainfodir}/io.github.joss943.LinXdiagram.metainfo.xml

%changelog
* Fri Oct 23 2026 LinXdiagram - 1.0.0-1
- Première version.
