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
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.sile
            pythonEnv
            pkgs.git
            pkgs.curl
            pkgs.jq
          ];
          shellHook = ''
            export USE_FLAKE=''${USE_FLAKE:-true}
            echo "Dev shell ready: SILE $(sile --version | head -n1)"
          '';
        };
      });
}
