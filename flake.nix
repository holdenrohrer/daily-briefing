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
            pkgs.lua5_1
            pkgs.luarocks
            pkgs.unzip
            jbMonoTtf
          ];
          FONTCONFIG_FILE = fontsConf;
          shellHook = ''
            fc-cache -f >/dev/null 2>&1 || true
            # Optional: project-local LuaRocks tree (if you manually install rocks)
            mkdir -p sile/lua_modules
            if command -v luarocks >/dev/null 2>&1; then
              eval "$(luarocks --lua-version 5.1 --tree sile/lua_modules path)" >/dev/null 2>&1 || true
            fi
            echo "Dev shell ready: SILE $(sile --version | head -n1)"
          '';
        };
      });
}
