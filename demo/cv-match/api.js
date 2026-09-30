// Scripted responses of the match-jobs function for the demo (the sample CV is the comp_bio_postdoc test persona)
const personas = require('../../supabase/functions/match-jobs/testdata/personas.json');

const profile = personas.find(p => p.name === 'comp_bio_postdoc').profile;

const matches = [
  { job_id: 'HKU-537164', score: 94, fit: 'strong',
    why: 'Your PhD in bioinformatics and two years building single-cell and spatial transcriptomics pipelines are exactly what a bioinformatics postdoc asks for.',
    gaps: ['The post sits in a public health institute, so experience with population health data would help'] },
  { job_id: 'HKU-534998', score: 88, fit: 'strong',
    why: 'A research assistant professorship in biomedical sciences is a natural next step: six genomics papers, two first-author, and your own methods work on epigenetics in stem cells.',
    gaps: ['These posts usually expect some grant-writing experience; mention any funding you helped win'] },
  { job_id: 'CUHK-39dadbd6a3', score: 82, fit: 'good',
    why: 'Your single-cell and cancer genomics analysis in Python and R fits a postdoctoral role in biomedical sciences research.',
    gaps: ["Check the ad for the lab's research area; some biomedical postdocs expect wet-lab skills"] },
  { job_id: 'HKU-536890', score: 78, fit: 'good',
    why: 'Your machine learning, statistics and HPC skills carry over well to a data scientist role analysing health data.',
    gaps: ['This is a research officer post rather than an academic track'] },
  { job_id: 'CITYU-ur-t16126', score: 74, fit: 'good',
    why: 'Your deep learning work on genomics data (PyTorch) fits a data science postdoc, and your sequencing experience gives you an applied domain.',
    gaps: ['Highlight your machine learning methods more than the biology'] },
  { job_id: 'HKU-537311', score: 70, fit: 'good',
    why: 'Your omics pipelines and cancer genomics experience are close to biomarker discovery work.',
    gaps: ["The post centres on proteomics; mass spectrometry isn't in your CV"] },
  { job_id: 'HKU-536261', score: 62, fit: 'possible',
    why: 'Your statistics background and large-scale data analysis could suit the post-doctoral level of this biostatistics post.',
    gaps: ['Formal training in epidemiology is usually expected'] },
  { job_id: 'CITYU-ur-t04824', score: 58, fit: 'possible',
    why: 'A data science postdoc where your machine learning and sequencing-data experience would be an asset.',
    gaps: ["Your CV doesn't show computer science publications"] },
];

module.exports = {
  profile: { ok: true, profile },
  match: {
    ok: true,
    matches,
    advice: 'Postdoctoral and research assistant professor posts in biomedical sciences and public health fit you best. Tenure-track faculty posts usually ask for a longer record of independent research.',
    open_jobs: 1546,
    considered: 40,
    updated: '2026-10-01',
  },
};
