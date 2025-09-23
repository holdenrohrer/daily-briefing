{
  description = "SILE + Python environment for Holden's Daily Report";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3;
        pythonEnv = python.withPackages (ps: with ps; [
          requests
          feedparser
          beautifulsoup4
          lxml
          pandas
          matplotlib
          pillow
          pyyaml
        ]);
        jbMonoTtf = pkgs.runCommand "jetbrains-mono-ttf-only" {} ''
          set -eu
          outdir="$out/share/fonts/truetype"
          mkdir -p "$outdir"
          find ${pkgs.jetbrains-mono}/share/fonts -type f \( -iname '*.ttf' -o -iname '*.otf' \) -exec cp -v '{}' "$outdir/" \;
        '';
        fontsConf = pkgs.makeFontsConf { fontDirectories = [ jbMonoTtf ]; };
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.sile
            pythonEnv
            pkgs.git
            pkgs.curl
            pkgs.jq
            pkgs.fontconfig
            pkgs.luarocks
            jbMonoTtf
          ];
          FONTCONFIG_FILE = fontsConf;
          shellHook = ''
            fc-cache -f >/dev/null 2>&1 || true
            # Ensure SILE framebox package is available locally for \use[module=packages.framebox]
            mkdir -p sile/lua_modules
            if ! luarocks --lua-version 5.1 --tree sile/lua_modules show framebox.sile >/dev/null 2>&1; then
              echo "Installing LuaRock framebox.sile into sile/lua_modules (Lua 5.1)..."
              luarocks --lua-version 5.1 --tree sile/lua_modules install framebox.sile || true
            fi
            echo "Dev shell ready: SILE $(sile --version | head -n1)"
          '';
        };
      });
}
