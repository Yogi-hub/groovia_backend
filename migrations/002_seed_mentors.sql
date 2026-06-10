-- 002_seed_mentors.sql
-- Dummy mentor data for local development. Diverse countries, categories, languages.
-- Run after 001_init_slice0.sql. Safe to re-run — ON CONFLICT (slug) DO NOTHING.

INSERT INTO mentors (
  slug, display_name, headline, bio,
  expertise_country_codes, expertise_categories, languages, professional_domains,
  booking_url, years_lived_experience
) VALUES
  -- ---------- Netherlands ----------
  (
    'maya-singh',
    'Maya Singh',
    'Software Engineer who moved from India to the Netherlands (Blue Card)',
    'I navigated the Dutch Blue Card process while changing jobs. Happy to share what I learned about paperwork, timing, and avoiding pitfalls.',
    ARRAY['NL']::CHAR(2)[],
    ARRAY['job_career', 'visa_pr'],
    ARRAY['en', 'hi'],
    ARRAY['IT'],
    'maya-singh', 4
  ),
  (
    'priya-mehta',
    'Priya Mehta',
    'Masters at TU Eindhoven, now ML Engineer at ASML',
    'Study-abroad route: application strategy, scholarship hunting, and the post-study work visa (zoekjaar).',
    ARRAY['NL']::CHAR(2)[],
    ARRAY['study_abroad', 'job_career'],
    ARRAY['en', 'hi'],
    ARRAY['Engineering', 'AI/ML'],
    'priya-mehta', 3
  ),
  (
    'lars-jansen',
    'Lars Jansen',
    'Relocation specialist — settling into Amsterdam',
    'Housing in Amsterdam is brutal. I help newcomers find a place, register at the gemeente, set up DigiD, banking, healthcare.',
    ARRAY['NL']::CHAR(2)[],
    ARRAY['life_settling'],
    ARRAY['en', 'nl'],
    ARRAY['Operations'],
    'lars-jansen', 8
  ),

  -- ---------- Germany ----------
  (
    'rohan-kapoor',
    'Rohan Kapoor',
    'Product Manager in Berlin (Skilled Worker visa)',
    'Helped 50+ folks land PM roles in Berlin. Specialism: visa interviews + salary negotiation for non-EU PMs.',
    ARRAY['DE']::CHAR(2)[],
    ARRAY['job_career'],
    ARRAY['en', 'hi', 'de'],
    ARRAY['Product'],
    'rohan-kapoor', 6
  ),
  (
    'fatima-rahman',
    'Fatima Rahman',
    'Healthcare professional — Germany work visa route',
    'Nurses, doctors, allied health: the Approbation process, B2 German requirement, and how to land your first hospital role.',
    ARRAY['DE']::CHAR(2)[],
    ARRAY['job_career', 'visa_pr'],
    ARRAY['en', 'ur', 'de'],
    ARRAY['Healthcare'],
    'fatima-rahman', 5
  ),
  (
    'arjun-iyer',
    'Arjun Iyer',
    'Masters in Computer Science, TU Munich',
    'I went from a tier-2 Indian engineering college to TUM on scholarship. Application strategy, German B1, student life.',
    ARRAY['DE']::CHAR(2)[],
    ARRAY['study_abroad'],
    ARRAY['en', 'hi', 'ta', 'de'],
    ARRAY['Engineering'],
    'arjun-iyer', 2
  ),

  -- ---------- Canada ----------
  (
    'sara-okonkwo',
    'Sara Okonkwo',
    'PR in Canada via Express Entry — finance professional',
    'CRS score optimization, IELTS prep, document checklist for ECA + PR. Toronto-based.',
    ARRAY['CA']::CHAR(2)[],
    ARRAY['visa_pr', 'job_career'],
    ARRAY['en', 'fr'],
    ARRAY['Finance'],
    'sara-okonkwo', 5
  ),
  (
    'daniel-park',
    'Daniel Park',
    'Software Engineer — Vancouver tech scene + LMIA',
    'Moved from Seoul to Vancouver on LMIA, transitioned to PR. Tech job market reality, salaries, neighborhoods.',
    ARRAY['CA']::CHAR(2)[],
    ARRAY['job_career', 'life_settling'],
    ARRAY['en', 'ko'],
    ARRAY['IT'],
    'daniel-park', 4
  ),

  -- ---------- UK ----------
  (
    'aditi-banerjee',
    'Aditi Banerjee',
    'Skilled Worker visa to UK — research scientist',
    'Sponsoring employers, salary thresholds, dependent visas, switching from Student to Skilled Worker.',
    ARRAY['GB']::CHAR(2)[],
    ARRAY['visa_pr', 'job_career'],
    ARRAY['en', 'bn', 'hi'],
    ARRAY['Research', 'Healthcare'],
    'aditi-banerjee', 7
  ),
  (
    'james-okafor',
    'James Okafor',
    'Global Talent visa holder — early-stage founder',
    'Got the UK Global Talent visa as a Nigerian tech founder. Endorsing bodies, evidence pack, founder visa alternatives.',
    ARRAY['GB']::CHAR(2)[],
    ARRAY['visa_pr'],
    ARRAY['en'],
    ARRAY['Product', 'Startups'],
    'james-okafor', 3
  ),

  -- ---------- USA ----------
  (
    'vivek-shah',
    'Vivek Shah',
    'H1B lottery to Green Card — 12 years in the US',
    'I survived 6 H1B lotteries, an L1 transfer, EB2-NIW filing. Honest take on the wait + employer dependence.',
    ARRAY['US']::CHAR(2)[],
    ARRAY['visa_pr', 'job_career'],
    ARRAY['en', 'hi', 'gu'],
    ARRAY['IT'],
    'vivek-shah', 12
  ),
  (
    'emily-chen',
    'Emily Chen',
    'F1 student → OPT → STEM extension — Bay Area',
    'University selection for STEM grads aiming at US tech. OPT/CPT, employer red flags, internship hunting timeline.',
    ARRAY['US']::CHAR(2)[],
    ARRAY['study_abroad', 'job_career'],
    ARRAY['en', 'zh'],
    ARRAY['IT', 'Engineering'],
    'emily-chen', 4
  ),

  -- ---------- Australia ----------
  (
    'ravi-pillai',
    'Ravi Pillai',
    'Skilled Independent visa (189) — Melbourne',
    'PR via points-based system. Skills assessment, EOI, state nomination. Cost of moving from India to AU.',
    ARRAY['AU']::CHAR(2)[],
    ARRAY['visa_pr'],
    ARRAY['en', 'hi', 'ml'],
    ARRAY['Engineering'],
    'ravi-pillai', 6
  ),

  -- ---------- Multi-country ----------
  (
    'sophie-laurent',
    'Sophie Laurent',
    'Career across EU — France, Germany, Belgium',
    'I worked in 3 EU countries in 10 years. EU Blue Card, intra-EU moves, taxation, family relocations.',
    ARRAY['DE', 'FR', 'BE']::CHAR(2)[],
    ARRAY['job_career', 'visa_pr', 'life_settling'],
    ARRAY['en', 'fr', 'de'],
    ARRAY['Consulting'],
    'sophie-laurent', 10
  )
ON CONFLICT (slug) DO NOTHING;
