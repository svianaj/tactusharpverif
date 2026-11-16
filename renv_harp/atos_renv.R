##############################################################
# Load renv from bootstrap library FIRST
##############################################################

bootstrap_lib <- file.path(getwd(), ".bootstrap_lib")

if (!dir.exists(bootstrap_lib)) {
  stop("Bootstrap library not found: ", bootstrap_lib)
}

.libPaths(c(bootstrap_lib, .libPaths()))

library(renv)

##############################################################
# Now enforce project-only library
##############################################################

Sys.setenv(
  RENV_CONFIG_USE_CACHE = "FALSE",
  RENV_PATHS_LIBRARY = file.path(getwd(), "renv/library"),
  RENV_PATHS_CACHE   = file.path(getwd(), "renv/cache")
)

.libPaths(file.path(getwd(), "renv/library"))

options(
  repos = c(CRAN = "https://cloud.r-project.org"),
  renv.verbose = TRUE
)

Sys.setenv(ARROW_R_ALLOW_CPP17 = "true")

# Install packages
##############################################################

harp_packages <- c(
  "harphub/harp@develop",
  "harphub/harpCore@develop",
  "harphub/harpIO@develop",
  "harphub/harpPoint@develop",
  "harphub/harpVis@develop",
  "harphub/ggsonde@master",
  "harphub/harpSpatial@develop"
)

cran_packages <- c(
  "argparse","cowplot","dplyr","forcats","ggnewscale","gridExtra",
  "here","lubridate","ncdf4","pals","pracma","purrr","RColorBrewer",
  "RSQLite","scales","scico","shiny","shinyWidgets","stringr","tidyr","yaml"
)

# Prevent renv from upgrading transitive dependencies
Sys.setenv(RENV_CONFIG_INSTALL_TRANSITIVE = "FALSE")

renv::init(bare = TRUE)
renv::snapshot(type = "all", prompt = FALSE, force = TRUE)

# Pin arrow first, bundled with harp packages so resolver sees it together
renv::install(c("arrow@14.0.0.1", harp_packages))
renv::record(list(arrow = "14.0.0.1"))

renv::install(cran_packages)
renv::snapshot(type = "all", prompt = FALSE, force = TRUE)


##############################################################
# Snapshot
##############################################################

cat("=== renv setup complete ===\n")


