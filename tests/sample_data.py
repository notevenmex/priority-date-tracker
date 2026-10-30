"""Made-up cutoffs shared by the synthetic HTML and PDF bulletins."""

FAM_HEADER = ["Family-Sponsored", "All Chargeability Areas Except Those Listed", "CHINA-mainland born",
              "INDIA", "MEXICO", "PHILIPPINES"]
EMP_HEADER = ["Employment-based", "All Chargeability Areas Except Those Listed", "CHINA-mainland born",
              "INDIA", "MEXICO", "PHILIPPINES"]
FA_FAM = [["F1", "08NOV16", "08NOV16", "08NOV16", "22APR05", "01MAR13"],
          ["F2A", "01FEB24", "01FEB24", "01FEB24", "01FEB23", "01FEB24"],
          ["F2B", "22SEP16", "22SEP16", "22SEP16", "01MAY09", "22OCT12"],
          ["F3", "22JUL11", "22JUL11", "22JUL11", "01OCT01", "08JAN05"],
          ["F4", "08JAN08", "08JAN08", "08AUG06", "01APR01", "22APR05"]]
DF_FAM = [["F1", "01SEP17", "01SEP17", "01SEP17", "01APR07", "15OCT15"],
          ["F2A", "22OCT25", "22OCT25", "22OCT25", "01FEB25", "22OCT25"],
          ["F2B", "01JAN17", "01JAN17", "01JAN17", "01FEB10", "01OCT13"],
          ["F3", "01DEC12", "01DEC12", "01DEC12", "01MAY02", "01JUN06"],
          ["F4", "01JAN09", "01JAN09", "22JAN07", "01MAR02", "01JAN08"]]
FA_EMP = [["1st", "C", "15FEB23", "15APR22", "C", "C"],
          ["2nd", "01APR24", "01SEP21", "15JUL13", "01APR24", "01APR24"],
          ["3rd", "22APR23", "01MAY21", "22MAY13", "22APR23", "01FEB23"],
          ["Other Workers", "01JUN21", "01JAN18", "22MAY13", "01JUN21", "01JUN21"],
          ["4th", "01JAN21", "01JAN21", "01JAN21", "01JAN21", "01JAN21"],
          ["Certain Religious Workers", "U", "U", "U", "U", "U"],
          ["5th Unreserved<br/>(including C5, T5, I5, R5, NU, RU)", "C", "22JAN14", "01MAY22", "C", "C"],
          ["5th Set Aside:<br/>Rural (20%, including NR, RR)", "C", "C", "C", "C", "C"],
          ["5th Set Aside:<br/>High Unemployment (10%, including NH, RH)", "C", "C", "C", "C", "C"],
          ["5th Set Aside:<br/>Infrastructure (2%, including RI)", "C", "C", "C", "C", "C"]]
DF_EMP = [[r[0]] + ["C" if v == "U" else v for v in r[1:]] for r in FA_EMP]
