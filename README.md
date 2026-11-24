# BR-dict

Dicionário de português do Brasil para o desktop Linux, feito em GTK4/libadwaita e baseado no [Wikcionário](https://pt.wiktionary.org).

<img width="590" height="625" alt="satty-20261119-132303" src="https://github.com/user-attachments/assets/eb2daa51-8e6b-49f7-9121-bc5c7fd80c3d" /> <img width="593" height="629" alt="satty-20261119-132400" src="https://github.com/user-attachments/assets/cf428cbc-af6a-4974-a2c2-8cb6f46748e3" />



O BR-dict é uma alternativa ao **GNOME Dicionário** (`gnome-dictionary`) para quem precisa consultar palavras em português. O GNOME Dicionário depende de servidores DICT, que praticamente não têm conteúdo em português. O BR-dict busca as definições direto no Wikcionário em português e se integra ao visual do GNOME.

## Recursos

- **Definições completas:** classes gramaticais, acepções numeradas, exemplos de uso, sinônimos, antônimos e etimologia.
- **Navegação entre verbetes:** as palavras nas definições são links. Clique para abrir o verbete e use o botão Voltar para retornar.
- **Sugestões:** se a palavra não existir ou estiver escrita errado, o app mostra sugestões parecidas ("Você quis dizer").
- **Cache local:** as palavras já consultadas ficam salvas e continuam disponíveis sem internet.
- **Modo offline (opcional):** baixa o conteúdo do Wikcionário e gera um banco local, assim as consultas funcionam sem conexão.
- **Atualização automática:** o app avisa quando sai uma nova versão no GitHub e pode instalá-la sozinho (no Arch Linux).
- **Abrir no Wikcionário:** leva o verbete atual para o navegador.

## Instalação

### Arch Linux e derivados

Baixe o pacote `br-dict-<versão>-any.pkg.tar.zst` na [página de releases](https://github.com/narayanls/BR-dict/releases/latest) e instale:

```sh
sudo pacman -U br-dict-*-any.pkg.tar.zst
```

Depois disso, as próximas versões podem ser instaladas pelo próprio app.

### Rodando direto do código-fonte

Instale as dependências (`python`, `python-gobject`, `gtk4` e `libadwaita` 1.5 ou mais recente) e rode:

```sh
cd BR-dict/usr/share/br-dict
python3 main.py
```

Desse jeito o app não se atualiza sozinho. Ele só avisa quando há uma versão nova.

## Uso

Abra o **BR-dict** pelo menu de aplicativos, digite uma palavra e tecle <kbd>Enter</kbd>. Também é possível abrir uma palavra pelo terminal:

```sh
br-dict saudade
```

| Atalho | Ação |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> ou <kbd>Ctrl</kbd>+<kbd>L</kbd> | Ir para o campo de busca |
| <kbd>Alt</kbd>+<kbd>←</kbd> | Voltar ao verbete anterior |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Sair |

### Modo offline

No menu principal, escolha **Modo offline…** e clique em **Baixar**. O app baixa o dump oficial do Wikcionário e gera um banco local só com a parte em português. O processo leva alguns minutos, mas você pode continuar usando o app enquanto isso.

Com o modo offline ativo, a ordem de busca é esta:

1. banco offline;
2. cache de consultas recentes;
3. Wikcionário online, para palavras que não estão no banco nem no cache.

### Atualizações

O BR-dict verifica se há uma nova versão alguns segundos depois de abrir. Para verificar na hora, use **Verificar atualizações** no menu principal. Quando houver uma versão nova, o app mostra as novidades e oferece a opção **Atualizar**: ele baixa o pacote, confere o checksum e instala com o `pacman`. Nesse momento o sistema pede a senha de administrador. Depois, é só reiniciar o app.

A instalação automática precisa do `pacman` e do `pkexec` (polkit). Em outros sistemas, ou rodando pelo código-fonte, o app só avisa e leva você para a página do release.

### Onde ficam os dados

| Arquivo | Conteúdo |
| --- | --- |
| `~/.cache/br-dict/cache.db` | Cache das palavras consultadas (pode ser limpo pelo menu) |
| `~/.local/share/br-dict/offline.db` | Banco do modo offline |
| `~/.cache/br-dict/updates/` | Pacote baixado durante uma atualização (é apagado depois de instalado) |

## 🛠️ Construído com

- [Python 3](https://www.python.org) + [PyGObject](https://pygobject.gnome.org)
- [GTK4](https://gtk.org) + [Adwaita (libadwaita)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
- Vibe Coding:
  Claude Sonnet foi usada para geração de código. O programa foi revisado e testado por humanos.
---

## Licença

O código do BR-dict é distribuído sob a [GPL-3.0](LICENSE).

As definições vêm do [Wikcionário](https://pt.wiktionary.org) e estão licenciadas sob [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.pt_BR).
