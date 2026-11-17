/* ============================================================
   Lexical Multi-dimensional Analysis
   Project: cl_st2_ph1_fernanda

   Expected input:
     counts.txt

   Expected counts.txt format:
     No header
     Space-separated
     Columns:
       filename year_chapter v000001-v000218

   Example:
     t000001 2009_c4 0 0 0 0 ...
   ============================================================ */


/* BEGINNING PART 1 */
/* === EDIT BELOW ====*/

%let project = cl_st2_ph1_fernanda ;

%let myfolder = &project ;

%let sasusername = u63529080 ;

%let whereisit = /home/&sasusername ;   /* online */

options fmtsearch=(work library);

/* enter the variable ID corresponding to the last keyword variable */
%let lastkeywordvar = v000218 ;

/* enter number of factors to extract */
%let extractfactors = 4 ;

%let factorvars = fac1-fac&extractfactors ;

/* enter min loading cutoff */
%let minloading = .3 ;

/* enter min communality cutoff */
%let communalcutoff = .15 ;

/* enter number of clusters to extract */
%let extractclusters = 2 ;

/* enter name of primary fixed var */
%let primaryfixedvar = year_chapter ;

/* END PART 1 */


/* BEGINNING PART 2 */
/* Read merged binary keyword matrix */

DATA &project;
  INFILE "&whereisit/&myfolder/counts.txt"
         dlm=' ' dsd truncover;

  LENGTH
      filename $7
      year_chapter   $7
      v000001 - &lastkeywordvar 3
  ;

  INPUT
      filename :$7.
      year_chapter   :$7.
      v000001 - &lastkeywordvar
  ;
RUN;

/* check for missing values */
proc means data=&project n nmiss;
run;


/* remove lines that are all zeros */
/* speed up by picking a single line of data to rotate */
data temp (DROP= filename year_chapter );
set &project ;
if _n_ <=1 ;
run;

proc transpose data=temp out= rot ;
run;

proc sql noprint;
    select _name_ into :names separated by ' + ' from rot ;
quit;

%put &names;

data &project (drop=total);
set &project;
total= &names ;
if total > 0 ;
run;

data temp (DROP= filename year_chapter );
set &project ;
if _n_ <=1 ;
run;

proc transpose data=temp out= rot ;
run;

proc sql noprint;
    select _name_ into :names separated by ' ' from rot ;
quit;

/* END PART 2 */


/* BEGINNING PART 7 */
/* Polychoric correlations */

OPTIONS VALIDVARNAME=ANY;

proc corr data = &project outplc = polychor polychoric noprint;
var &names ;
run;

/* END PART 7 */


/* BEGINNING PART 8 */
/* Turn missing correlation values to zeros */

proc stdize data = polychor out=polychor reponly missing=0;
run;

/* END PART 8 */


/* BEGINNING PART 9 */
/* Initial factor analysis */

/* number of observations IN THE DATA */
data _NULL_;
    if 0 then set &project nobs=n;
    call symputx('nobs',n);
    stop;
run;

%put nobs=&nobs ;

/* get variable list for factor */

data temp (DROP= filename year_chapter );
set &project ;
if _n_ <=1 ;
run;

proc transpose data=temp out= rot ;
run;

proc sql ;
    select _name_ into :names separated by ' ' from rot ;
quit;

/* unrotated, before dropping low communalities */

proc datasets library=work nolist;
delete fout;
run;

ODS EXCLUDE NONE;

proc factor fuzz=0.3 data= polychor (type=corr) OUTSTAT= fout NOPRINT
method=principal
plots=scree
mineigen=1
reorder
heywood
nfactors=100
nobs=&nobs;
var &names ;
run;

/* END PART 9 */


/* BEGINNING PART 10 */
/* Find low communalities */

data fout2;
    set fout (where=(_TYPE_="COMMUNAL"));
run;

proc transpose data=fout2 out=communal;
id _TYPE_;
run;

/* list vars to drop */
proc sql ;
    select _name_ into :lowcomm separated by ' ' from communal
        where communal < &communalcutoff ;
quit;

/* list vars to keep */
ODS EXCLUDE NONE ;

proc sql ;
    select _name_ into :highcomm separated by ' ' from communal
        where communal >= &communalcutoff ;
quit;

/* save communalities to spreadsheet */

PROC SORT data=communal (keep= _name_ communal);
BY communal;
RUN;

PROC EXPORT
  DATA= WORK.communal
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/communalities.tsv"
  REPLACE;
RUN;

/* END PART 10 */


/* BEGINNING PART 12 */
/* Scree plot */

data fout2;
  set fout (where=(_TYPE_="EIGENVAL"));
run;

proc transpose data=fout2 out= fout3 (drop = _NAME_);
id _TYPE_;
run;

data fout4 ;
set fout3 ;
factor = _n_;
if factor <= 20 ;
run;

/* delete existing scree files */
%macro delete_scree(howmany);
%do i=1 %to &howmany;

FILENAME temp "/home/&sasusername/&myfolder/scree_1&i..png";
DATA _NULL_;
  rc=FDELETE('temp');
RUN;

FILENAME temp "/home/&sasusername/&myfolder/scree_2&i..png";
DATA _NULL_;
  rc=FDELETE('temp');
RUN;

%end;
%mend delete_scree;

%delete_scree(9)
;

/* create scree files */

ods listing gpath="&whereisit/&myfolder/";
ods graphics on / reset imagename="scree_1" imagefmt=png;

title "Scree plot";

proc sgplot data= fout4 ;
  series x=factor y=EIGENVAL / markers datalabel=EIGENVAL
  markerattrs=(symbol = circle color = blue size = 10px);
   xaxis grid values=(1 TO 20) label='Factor';
   yaxis grid label='Eigenvalue';
   refline &extractfactors / axis = x lineattrs = (color = red pattern = dash);
run;

title;

ods listing gpath="&whereisit/&myfolder/";
ods graphics on / reset imagename="scree_2" imagefmt=png;

title "Scree plot";

proc sgplot data= fout4 ;
  series x=factor y=EIGENVAL / markers datalabel=factor
  markerattrs=(symbol = circle color = blue size = 10px);
  yaxis grid label='Eigenvalue';
  xaxis grid values=(1 TO 20) label='Factor';
  refline &extractfactors / axis = x lineattrs = (color = red pattern = dash);
run;

title;

/* determine the number of factors and enter number in the header of this program */

/* END PART 12 */


/* BEGINNING PART 13 */
/* Rotated factor analysis without low-communality variables */

proc datasets library=work nolist;
delete rotatedfinal;
run;

proc factor fuzz=0.3 data= polychor (type=corr) OUTSTAT= rotatedfinal NOPRINT
method=principal
scree
mineigen=0
priors=max
nfactors= &extractfactors
rotate=promax
heywood
nobs=&nobs;
var &highcomm ;
run;

/* END PART 13 */


/* BEGINNING PART 14 */
/* Loadings table */

/*

https://stats.idre.ucla.edu/sas/output/factor-analysis/
Rotated Factor Pattern – This table contains the rotated factor loadings, which are the correlations between the variable and the factor.  Because these are correlations, possible values range from -1 to +1.
in the outstat data file, the rotated factor pattern appears as PREROTAT. The standardized regression coefficients appear as PATTERN.
Use PREROTAT in the outstat data file.

https://documentation.sas.com/?docsetId=statug&docsetTarget=statug_factor_details02.htm&docsetVersion=15.1&locale=en

PREROTAT: prerotated factor pattern.
PATTERN: factor pattern. (regression coefficients)

PREROTAT: prerotated factor pattern. =>   Stat.Factor.OrthRotFactPat
PATTERN: factor pattern. =>  Stat.Factor.ObliqueRotFactPat

*/

OPTIONS VALIDVARNAME=ANY;

data rotated2;
  set rotatedfinal (where=(_TYPE_="PATTERN"));
run;

proc transpose data=rotated2 out= rotated2 ;
id _NAME_ ;
run;

OPTIONS VALIDVARNAME=ANY;

data rotated3;
   set rotated2;
      loaded = 0 ;

        if     abs(factor1) > abs(factor2)
           AND abs(factor1) > abs(factor3)
           AND abs(factor1) > abs(factor4)
           AND abs(factor1) > abs(factor5)
           AND abs(factor1) > abs(factor6)
           AND abs(factor1) > abs(factor7)
           AND abs(factor1) > abs(factor8)
           AND abs(factor1) > abs(factor9)
           AND factor1 > 0 AND abs(factor1) >= "&minloading"
        then do; factor = 'fac1'; pole = 1; loaded = 1; end ;

   else if     abs(factor2) > abs(factor1)
           AND abs(factor2) > abs(factor3)
           AND abs(factor2) > abs(factor4)
           AND abs(factor2) > abs(factor5)
           AND abs(factor2) > abs(factor6)
           AND abs(factor2) > abs(factor7)
           AND abs(factor2) > abs(factor8)
           AND abs(factor2) > abs(factor9)
           AND factor2 > 0 AND abs(factor2) >= "&minloading"
        then do; factor = 'fac2'; pole = 1; loaded = 1; end ;

   else if     abs(factor3) > abs(factor1)
           AND abs(factor3) > abs(factor2)
           AND abs(factor3) > abs(factor4)
           AND abs(factor3) > abs(factor5)
           AND abs(factor3) > abs(factor6)
           AND abs(factor3) > abs(factor7)
           AND abs(factor3) > abs(factor8)
           AND abs(factor3) > abs(factor9)
           AND factor3 > 0 AND abs(factor3) >= "&minloading"
        then do; factor = 'fac3'; pole = 1; loaded = 1; end ;

   else if     abs(factor4) > abs(factor1)
           AND abs(factor4) > abs(factor2)
           AND abs(factor4) > abs(factor3)
           AND abs(factor4) > abs(factor5)
           AND abs(factor4) > abs(factor6)
           AND abs(factor4) > abs(factor7)
           AND abs(factor4) > abs(factor8)
           AND abs(factor4) > abs(factor9)
           AND factor4 > 0 AND abs(factor4) >= "&minloading"
        then do; factor = 'fac4'; pole = 1; loaded = 1; end ;

   else if     abs(factor5) > abs(factor1)
           AND abs(factor5) > abs(factor2)
           AND abs(factor5) > abs(factor3)
           AND abs(factor5) > abs(factor4)
           AND abs(factor5) > abs(factor6)
           AND abs(factor5) > abs(factor7)
           AND abs(factor5) > abs(factor8)
           AND abs(factor5) > abs(factor9)
           AND factor5 > 0 AND abs(factor5) >= "&minloading"
        then do; factor = 'fac5'; pole = 1; loaded = 1; end ;

   else if     abs(factor6) > abs(factor1)
           AND abs(factor6) > abs(factor2)
           AND abs(factor6) > abs(factor3)
           AND abs(factor6) > abs(factor4)
           AND abs(factor6) > abs(factor5)
           AND abs(factor6) > abs(factor7)
           AND abs(factor6) > abs(factor8)
           AND abs(factor6) > abs(factor9)
           AND factor6 > 0 AND abs(factor6) >= "&minloading"
        then do; factor = 'fac6'; pole = 1; loaded = 1; end ;

   else if     abs(factor7) > abs(factor1)
           AND abs(factor7) > abs(factor2)
           AND abs(factor7) > abs(factor3)
           AND abs(factor7) > abs(factor4)
           AND abs(factor7) > abs(factor5)
           AND abs(factor7) > abs(factor6)
           AND abs(factor7) > abs(factor8)
           AND abs(factor7) > abs(factor9)
           AND factor7 > 0 AND abs(factor7) >= "&minloading"
        then do; factor = 'fac7'; pole = 1; loaded = 1; end ;

   else if     abs(factor8) > abs(factor1)
           AND abs(factor8) > abs(factor2)
           AND abs(factor8) > abs(factor3)
           AND abs(factor8) > abs(factor4)
           AND abs(factor8) > abs(factor5)
           AND abs(factor8) > abs(factor6)
           AND abs(factor8) > abs(factor7)
           AND abs(factor8) > abs(factor9)
           AND factor8 > 0 AND abs(factor8) >= "&minloading"
        then do; factor = 'fac8'; pole = 1; loaded = 1; end ;

   else if     abs(factor9) > abs(factor1)
           AND abs(factor9) > abs(factor2)
           AND abs(factor9) > abs(factor3)
           AND abs(factor9) > abs(factor4)
           AND abs(factor9) > abs(factor5)
           AND abs(factor9) > abs(factor6)
           AND abs(factor9) > abs(factor7)
           AND abs(factor9) > abs(factor8)
           AND factor9 > 0 AND abs(factor9) >= "&minloading"
        then do; factor = 'fac9'; pole = 1; loaded = 1; end ;

  else  if     abs(factor1) > abs(factor2)
           AND abs(factor1) > abs(factor3)
           AND abs(factor1) > abs(factor4)
           AND abs(factor1) > abs(factor5)
           AND abs(factor1) > abs(factor6)
           AND abs(factor1) > abs(factor7)
           AND abs(factor1) > abs(factor8)
           AND abs(factor1) > abs(factor9)
           AND factor1 < 0 AND abs(factor1) >= "&minloading"
        then do; factor = 'fac1'; pole = -1; loaded = 1; end ;

   else if     abs(factor2) > abs(factor1)
           AND abs(factor2) > abs(factor3)
           AND abs(factor2) > abs(factor4)
           AND abs(factor2) > abs(factor5)
           AND abs(factor2) > abs(factor6)
           AND abs(factor2) > abs(factor7)
           AND abs(factor2) > abs(factor8)
           AND abs(factor2) > abs(factor9)
           AND factor2 < 0 AND abs(factor2) >= "&minloading"
        then do; factor = 'fac2'; pole = -1; loaded = 1; end ;

   else if     abs(factor3) > abs(factor1)
           AND abs(factor3) > abs(factor2)
           AND abs(factor3) > abs(factor4)
           AND abs(factor3) > abs(factor5)
           AND abs(factor3) > abs(factor6)
           AND abs(factor3) > abs(factor7)
           AND abs(factor3) > abs(factor8)
           AND abs(factor3) > abs(factor9)
           AND factor3 < 0 AND abs(factor3) >= "&minloading"
        then do; factor = 'fac3'; pole = -1; loaded = 1; end ;

   else if     abs(factor4) > abs(factor1)
           AND abs(factor4) > abs(factor2)
           AND abs(factor4) > abs(factor3)
           AND abs(factor4) > abs(factor5)
           AND abs(factor4) > abs(factor6)
           AND abs(factor4) > abs(factor7)
           AND abs(factor4) > abs(factor8)
           AND abs(factor4) > abs(factor9)
           AND factor4 < 0 AND abs(factor4) >= "&minloading"
        then do; factor = 'fac4'; pole = -1; loaded = 1; end ;

   else if     abs(factor5) > abs(factor1)
           AND abs(factor5) > abs(factor2)
           AND abs(factor5) > abs(factor3)
           AND abs(factor5) > abs(factor4)
           AND abs(factor5) > abs(factor6)
           AND abs(factor5) > abs(factor7)
           AND abs(factor5) > abs(factor8)
           AND abs(factor5) > abs(factor9)
           AND factor5 < 0 AND abs(factor5) >= "&minloading"
        then do; factor = 'fac5'; pole = -1; loaded = 1; end ;

   else if     abs(factor6) > abs(factor1)
           AND abs(factor6) > abs(factor2)
           AND abs(factor6) > abs(factor3)
           AND abs(factor6) > abs(factor4)
           AND abs(factor6) > abs(factor5)
           AND abs(factor6) > abs(factor7)
           AND abs(factor6) > abs(factor8)
           AND abs(factor6) > abs(factor9)
           AND factor6 < 0 AND abs(factor6) >= "&minloading"
        then do; factor = 'fac6'; pole = -1; loaded = 1; end ;

   else if     abs(factor7) > abs(factor1)
           AND abs(factor7) > abs(factor2)
           AND abs(factor7) > abs(factor3)
           AND abs(factor7) > abs(factor4)
           AND abs(factor7) > abs(factor5)
           AND abs(factor7) > abs(factor6)
           AND abs(factor7) > abs(factor8)
           AND abs(factor7) > abs(factor9)
           AND factor7 < 0 AND abs(factor7) >= "&minloading"
        then do; factor = 'fac7'; pole = -1; loaded = 1; end ;

   else if     abs(factor8) > abs(factor1)
           AND abs(factor8) > abs(factor2)
           AND abs(factor8) > abs(factor3)
           AND abs(factor8) > abs(factor4)
           AND abs(factor8) > abs(factor5)
           AND abs(factor8) > abs(factor6)
           AND abs(factor8) > abs(factor7)
           AND abs(factor8) > abs(factor9)
           AND factor8 < 0 AND abs(factor8) >= "&minloading"
        then do; factor = 'fac8'; pole = -1; loaded = 1; end ;

   else if     abs(factor9) > abs(factor1)
           AND abs(factor9) > abs(factor2)
           AND abs(factor9) > abs(factor3)
           AND abs(factor9) > abs(factor4)
           AND abs(factor9) > abs(factor5)
           AND abs(factor9) > abs(factor6)
           AND abs(factor9) > abs(factor7)
           AND abs(factor9) > abs(factor8)
           AND factor9 < 0 AND abs(factor9) >= "&minloading"
        then do; factor = 'fac9'; pole = -1; loaded = 1; end ;

run;

data rotated3 (KEEP= _NAME_ factor1-factor&extractfactors loaded factor pole );
set rotated3 ;
run;

data rotated4 ;
set rotated3 ;
if loaded = 1;
run;
quit;

%include "/home/&sasusername/&myfolder/word_labels_full_format.sas";

ods html file="&whereisit/&myfolder/loadtable_full.html";

%macro create_loadtable_full(howmany);
%do i=1 %to &howmany;

title "LOADINGS TABLE";
title2 "Factor &i pos" ;

data temp;
  set rotated4 ;
  where factor="fac&i" and pole=1 ;
run;

proc sort data=temp;
  by descending Factor&i ;
run;

proc print data=temp ;
  FORMAT _NAME_ $lexlabelsfull.;
  var _NAME_ Factor&i ;
run;

title "Factor &i neg" ;

data temp;
  set rotated4 ;
  where factor="fac&i" and pole=-1 ;
run;

proc sort data=temp;
  by Factor&i ;
run;

proc print data=temp ;
  FORMAT _NAME_ $lexlabelsfull.;
  var _NAME_ Factor&i ;
run;

%end;
%mend create_loadtable_full;

%create_loadtable_full(&extractfactors)

ods html close;
quit;

%include "/home/&sasusername/&myfolder/word_labels_format.sas";

ods html file="&whereisit/&myfolder/loadtable.html";

%macro create_loadtable(howmany);
%do i=1 %to &howmany;

title "LOADINGS TABLE";
title2 "Factor &i pos" ;

data temp;
  set rotated4 ;
  where factor="fac&i" and pole=1 ;
run;

proc sort data=temp;
  by descending Factor&i ;
run;

proc print data=temp ;
  FORMAT _NAME_ $lexlabels.;
  var _NAME_ Factor&i ;
run;

title "Factor &i neg" ;

data temp;
  set rotated4 ;
  where factor="fac&i" and pole=-1 ;
run;

proc sort data=temp;
  by Factor&i ;
run;

proc print data=temp ;
  FORMAT _NAME_ $lexlabels.;
  var _NAME_ Factor&i ;
run;

%end;
%mend create_loadtable;

%create_loadtable(&extractfactors)

ods html close;
quit;

PROC EXPORT
  DATA= WORK.rotated3
  DBMS=CSV
  OUTFILE="&whereisit/&myfolder/rotated.csv"
  REPLACE;
RUN;

/* END PART 14 */


/* BEGINNING PART 16 */
/* Factor scores */
/* no standardizing the data because it is binary */

data temp (DROP= filename year_chapter );
set &project ;
if _n_ <=1 ;
run;

proc transpose data=temp out= rot ;
run;

proc sql NOPRINT;
    select _name_ into :names separated by ' ' from rot ;
quit;

data rotated4;
set rotated3;
if loaded = 1;
run;

proc sort data=rotated4;
  by factor ;
run;

proc transpose data=rotated4 out=score;
  by factor ;
  id _NAME_ ;
  var pole;
run;

data score;
  _type_='SCORE';
  set score;
  drop _name_;
  rename factor=_name_;
run;

proc score data=&project score=score out=scores;
run;

/* turn missing values to zeros */

proc stdize data = scores out=scores reponly missing=0;
var &names ;
run;

proc sort data = scores ;
by filename ;
run;

data scores_grouped;
    set scores;
    length group $40;
    group = year_chapter;
run;

data scores_only (KEEP= filename year_chapter group &factorvars );
set scores_grouped ;
run;

/* fix variable order */
data scores_only;
 retain filename year_chapter group &factorvars;
 set scores_grouped;
run;

PROC EXPORT
  DATA= WORK.scores
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/&project._scores.tsv"
  REPLACE;
RUN;

PROC EXPORT
  DATA= WORK.scores_only
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/&project._scores_only.tsv"
  REPLACE;
RUN;


/* ANOVAS by year_chapter */

ODS EXCLUDE NONE;

ods html file="&whereisit/&myfolder/glm_meta.html";

%macro create_anovas(howmany);
%do i=1 %to &howmany;

OPTIONS VALIDVARNAME=ANY;
ods graphics off;

ods output OverallANOVA=overall_year_chapter_f&i ;
ods output FitStatistics=params_year_chapter_f&i ;
ods output ModelANOVA=anova_year_chapter_f&i ;
ods output Means=means_year_chapter_f&i ;

proc GLM data=scores;
    title GLM for dataset = &project year_chapter fac&i ;
    class year_chapter ;
    model fac&i = year_chapter ;
    means year_chapter ;
run;
quit;

ods output close;

ods graphics on;

%end;
%mend create_anovas;

%create_anovas(&extractfactors)

ods html close;
quit;


/* EXPORT ANOVAS */

ODS EXCLUDE NONE;

%macro export_anovas(howmany);
%do i=1 %to &howmany;

PROC EXPORT
  DATA= WORK.overall_year_chapter_f&i
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/overall_year_chapter_f&i..tsv"
  REPLACE;
RUN;

PROC EXPORT
  DATA= WORK.params_year_chapter_f&i
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/params_year_chapter_f&i..tsv"
  REPLACE;
RUN;

PROC EXPORT
  DATA= WORK.anova_year_chapter_f&i
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/anova_year_chapter_f&i..tsv"
  REPLACE;
RUN;

PROC EXPORT
  DATA= WORK.means_year_chapter_f&i
  DBMS=TAB
  OUTFILE="&whereisit/&myfolder/means_year_chapter_f&i..tsv"
  REPLACE;
RUN;

%end;
%mend export_anovas;

%export_anovas(&extractfactors)

quit;


/* ZIP OUTPUT FILES */

%let addcntzip = /home/u63529080/zip/output_&project..zip;

FILENAME temp "&addcntzip";

DATA _NULL_;
  rc=FDELETE('temp');
RUN;

data filelist;
run;

data filelist;
  length root dname $ 2048 filename $ 256 dir level 8;
  input root;
  retain filename dname ' ' level 0 dir 1;
cards4;
/home/u63529080/cl_st2_ph1_fernanda
;;;;
run;

data filelist;
  modify filelist;
  rc1=filename('tmp',catx('/',root,dname,filename));
  rc2=dopen('tmp');
  dir = 1 & rc2;

  if dir then do;
      dname=catx('/',dname,filename);
      filename=' ';
  end;

  replace;

  if dir;

  level=level+1;

  do i=1 to dnum(rc2);
    filename=dread(rc2,i);
    output;
  end;

  rc3=dclose(rc2);
run;

proc sort data=filelist;
  by root dname filename;
run;

proc print data=filelist;
run;

data _null_;

  set filelist;

  if dir=0;

  rc1=filename("in" , catx('/',root,dname,filename), "disk", "lrecl=1 recfm=n");
  rc1txt=sysmsg();

  rc2=filename(
      "out",
      "&addcntzip.",
      "ZIP",
      "lrecl=1 recfm=n member='" !! catx('/',dname,filename) !! "'"
  );
  rc2txt=sysmsg();

  do _N_ = 1 to 6;
    rc3=fcopy("in","out");
    rc3txt=sysmsg();

    if fexist("out") then leave;
    else sleeprc=sleep(0.5,1);
  end;

  rc4=fexist("out");
  rc4txt=sysmsg();

  put _N_ @12 (rc:) (=);

run;


/* delete all png, html, tsv, and csv files after zipping */

%let path=&whereisit/&myfolder;

FILENAME _folder_ "%bquote(&path.)";

data filenames(keep=memname);
  handle=dopen( '_folder_' );

  if handle > 0 then do;
    count=dnum(handle);

    do i=1 to count;
      memname=dread(handle,i);

      if scan(memname, 2, '.')='png'
      OR scan(memname, 2, '.')='html'
      OR scan(memname, 2, '.')='tsv'
      OR scan(memname, 2, '.')='csv'
      then output filenames;
    end;
  end;

  rc=dclose(handle);
run;

filename _folder_ clear;

data _null_;
set filenames;
fname = 'todelete';
rc = filename(fname, quote(cats("&path",'/',memname)));
rc = fdelete(fname);
rc = filename(fname);
run;

/* END OF PROGRAM */