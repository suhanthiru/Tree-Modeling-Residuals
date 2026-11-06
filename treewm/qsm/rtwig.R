# Correct the twig radii of TreeQSM models with rTwig, for a batch of trees.
#
# usage: Rscript rtwig.R <jobs.csv>
#   jobs.csv columns: tree_id, species_latin, qsm_mat, out_csv, and optionally twig_radius_mm
#
# For every tree it writes out_csv (one row per cylinder, rTwig column names) and a one-row
# sidecar <out_csv>.meta.csv with the twig radius used. The twig radius is twig_radius_mm when
# given, otherwise it comes from rTwig's `twigs` table: the species if listed, otherwise the
# "<Genus> spp." average.
# Smoothing is off: rTwig's default smooth = TRUE also moves cylinder start points, and v1.1
# changes radii only. Called by treewm/qsm/rtwig.py; it is not meant to be run by hand.

suppressPackageStartupMessages(library(rTwig))
data(twigs)

jobs <- read.csv(commandArgs(trailingOnly = TRUE)[1], stringsAsFactors = FALSE)
keep <- c("start.x", "start.y", "start.z", "axis.x", "axis.y", "axis.z", "end.x", "end.y", "end.z",
          "length", "radius", "OldRadius", "UnmodRadius", "parent", "extension", "added",
          "BranchOrder", "PositionInBranch", "branch", "modified")

twig_radius <- function(sp, given = NA) {
  if (!is.na(given)) return(list(r = as.numeric(given), src = "given"))
  if (is.na(sp) || sp == "") stop("no species and no twig radius given")
  hit <- twigs[twigs$scientific_name == sp, ]
  if (nrow(hit)) return(list(r = hit$radius_mm[1], src = sp))
  genus <- paste(strsplit(sp, " ")[[1]][1], "spp.")
  hit <- twigs[twigs$scientific_name == genus, ]
  if (nrow(hit)) return(list(r = hit$radius_mm[1], src = genus))
  stop("no twig radius in rTwig's table for ", sp)
}

for (i in seq_len(nrow(jobs))) {
  j <- jobs[i, ]
  t0 <- Sys.time()
  res <- tryCatch({
    tw <- twig_radius(j$species_latin, if ("twig_radius_mm" %in% names(j)) j$twig_radius_mm else NA)
    out <- as.data.frame(suppressMessages(
      run_rtwig(j$qsm_mat, twig_radius = tw$r, metrics = FALSE, smooth = FALSE, version = "2.3.0")))
    write.csv(out[, keep], j$out_csv, row.names = FALSE)
    secs <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
    write.csv(data.frame(tree_id = j$tree_id, species_latin = j$species_latin, twig_radius_mm = tw$r,
                         twig_source = tw$src, smooth = FALSE,
                         rtwig_version = as.character(packageVersion("rTwig")), n_cylinders = nrow(out),
                         seconds = secs),
              paste0(j$out_csv, ".meta.csv"), row.names = FALSE)
    sprintf("RTWIG ok %s twig %.2f mm (%s) %d cylinders %.0f s", j$tree_id, tw$r, tw$src, nrow(out), secs)
  }, error = function(e) sprintf("RTWIG error %s %s", j$tree_id, gsub("[\r\n]", " ", conditionMessage(e))))
  cat(res, "\n", sep = "")
  flush(stdout())
}
