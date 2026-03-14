"""
DSPy Signature for Entity Extraction

Extracts named entities from conversation/mission text and maps them to
Schema.org class names. The full Schema.org reference is injected into
the prompt at call time via the `schema_reference` input field.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

import dspy


class EntityEntryModel(BaseModel):
    """A single extracted entity.

    Both fields are Optional so partial LLM responses don't hard-fail.
    The extractor filters incomplete entries before storage.
    """
    name: Optional[str] = Field(
        default=None,
        description="The entity name as it appears in text. "
                    "Use the most complete proper name mentioned (e.g., 'Dr. Priya Nair' not 'Priya'). "
                    "Must be a proper noun — names of specific people, places, organizations, events."
    )
    schema_type: Optional[str] = Field(
        default="Thing",
        description="The most specific Schema.org class name for this entity. "
                    "Always prefer a subclass over its parent: "
                    "'Hospital' over 'Organization', 'Restaurant' over 'LocalBusiness', "
                    "'Movie' over 'CreativeWork', 'Festival' over 'Event'. "
                    "Use 'Thing' only as a last resort."
    )


class EntityExtractionResult(BaseModel):
    """Structured result from entity extraction."""
    entities: List[EntityEntryModel] = Field(
        default_factory=list,
        description="All named entities found in the text mapped to Schema.org class names. "
                    "Include people, organizations, places, events, and significant named objects. "
                    "Be thorough — extract every entity that could be useful for retrieval."
    )


class EntityExtractionSignature(dspy.Signature):
    """You are an entity extraction specialist. Extract all named entities from the
    text and classify each with the most specific Schema.org class.

    The `relevant_classes` field contains Schema.org classes retrieved by semantic
    similarity to this text — prioritize these when classifying entities.
    The full `schema_reference` is provided as a fallback for any class not listed.

    ALWAYS prefer the most specific subclass:
        'Hospital' not 'Organization', 'Festival' not 'Event',
        'Movie' not 'CreativeWork', 'MusicRecording' not 'MusicAlbum' for a single song,
        'Hotel' not 'LodgingBusiness', 'Restaurant' not 'FoodEstablishment'

    SCHEMA.ORG GAPS — classes that do NOT exist (use the alternative shown):
    - 'Animal' → use 'Taxon' (or 'Thing' as last resort)
    - 'Award'  → NOT a class; capture award names via the 'award' property (Text range)
                 on the winning Person/Organization/CreativeWork node
    - 'Podcast' → use 'PodcastSeries' for the show, 'PodcastEpisode' for episodes

    DO NOT EXTRACT:
    - Generic noun phrases ('the store', 'a hospital', 'some event', 'the platform')
    - Image captions or photo descriptions ('a woman in a garden', 'family photo')
    - Names with more than 4 words (likely image descriptions, not entity names)
    - Pronouns or vague references ('he', 'she', 'someone', 'they')
    - Roles without a name ('a nurse', 'the CEO', 'a teacher')
    - Abstract concepts, adjectives, or feelings ('happiness', 'success', 'support')
    - Dates and time expressions
    - Monetary amounts or prices ('$500', 'fifty dollars')

    Guidelines:
    - Use the most complete name form: 'Dr. Priya Nair' not 'Priya'
    - Use exact camelCase class names from the Schema.org reference
    - Only fall back to 'Organization', 'Place', 'CreativeWork', 'Event', or 'Thing'
      when no specific subclass fits

    ENTITY TYPES — reference examples (full coverage via relevant_classes + schema_reference):


    People (Person):
      e.g., 'Alex Rivera', 'Dr. Priya Nair', 'Marco Bellini', 'Kenji Tanaka', 'Lena Voss'

    Organizations — use the most specific subclass, NOT the generic 'Organization':
      For-profit companies:
        Corporation:              'Helix Systems', 'Lighthouse Films'
        Airline:                  'United Airlines', 'Lufthansa'
        Store:                    'IKEA', 'Target'  ← retail stores
        FinancialService:         'Merrill Lynch'  ← investment banks, brokerages
      Healthcare (also check CivicStructure — Hospital is a CivicStructure):
        Hospital:                 'Riverside Medical Center'
        Dentist:                  'Bright Smile Dental Clinic'
        Pharmacy:                 'Corner Pharmacy'
      Education:
        CollegeOrUniversity:      'Westbrook University'
        School:                   'Lincoln High School'  ← not CollegeOrUniversity
        Library:                  'Portland Public Library'
      Food & Hospitality:
        Restaurant:               "Tanaka's Kitchen"
        Hotel:                    'Grand Vista Hotel'  ← subclass of LodgingBusiness
      Financial:
        BankOrCreditUnion:        'Pacific Credit Union'
      Legal:
        LegalService:             'Mercer & Associates'
      Government:
        GovernmentOrganization:   'Portland City Council'
      Media & News:
        NewsMediaOrganization:    'The Daily Dispatch'
      Research:
        ResearchOrganization:     'Apex Research Institute'
      Arts & Entertainment:
        MusicGroup:               'The Velvet Circuit'
        PerformingGroup:          'Cascade Dance Company'  ← orchestras, dance companies
        EntertainmentBusiness:    'Regal Cinemas'  ← cinemas, clubs, entertainment venues
        SportsTeam:               'Portland Falcons'
        SportsOrganization:       'Pacific Coast League'  ← sports leagues, associations
      Other:
        NGO:                      'Open Horizons Foundation'
        LocalBusiness:            last resort for unnamed business categories

    Places — use the most specific subclass:
      City:                       'Portland', 'Chicago', 'Barcelona', 'Berlin'
      Country:                    'Brazil', 'Germany'
      AdministrativeArea:         'Oregon', 'Catalonia'  ← states, provinces, regions
      Park:                       'Cascades National Park'
      Airport:                    'Portland International Airport'
      Museum:                     'Natural History Museum'
      LandmarksOrHistoricalBuildings: 'Sagrada Família'
      TouristAttraction:          'Mesa Verde Trail'
      EventVenue:                 'Convention Center', 'Fox Theater'  ← general event spaces
      StadiumOrArena:             'Memorial Stadium'  ← sports venues
      MusicVenue:                 'The Blue Room'  ← dedicated music venues
      PerformingArtsTheater:      'Cascade Arts Theater'
      Landform:                   'Mount Rainier', 'Colorado River'  ← mountains, rivers, lakes, natural features
      Residence:                  "Alex Rivera's apartment", 'the Nair family home'  ← private residences

    Creative Works — use the most specific subclass:
      Movie:            '"The Silence of Glaciers"'
      Book:             '"Patterns of Rain"'
      MusicAlbum:       '"Echoes of Blue"'
      MusicRecording:   '"Midnight Rain"'  ← individual song/track, NOT an album
      TVSeries:         '"Harbor Watch"'
      PodcastSeries:    '"The Science Hour"'  ← 'Podcast' is NOT a Schema.org class
      Article:          '"Why Sleep Matters"'  ← blog posts, news articles, essays
      ScholarlyArticle: '"Neural Plasticity in Adults"'  ← academic/research papers
      Blog:             'The Portland Cook'  ← the blog itself (collection); posts → Article
      WebSite:          'helix.io', 'westbrook.edu'  ← a whole website
      Dataset:          'Portland Traffic Dataset'  ← structured data collections
      SoftwareSourceCode: 'NovaMind GitHub Repo'  ← code repositories
      Game:             '"Rift Chronicles"'  ← video games, board games
      Recipe:           "Kenji Tanaka's Ramen Recipe"  ← cooking/food recipes
      Review:           '"Review of The Silence of Glaciers"'  ← critical reviews, evaluations
      Message:          "Lena Voss's email to the team"  ← emails, letters, messages (named/referenced)

    Events — use the most specific subclass:
      Festival:         'North Star Film Festival'
      SportsEvent:      'Pacific Half Marathon'
      ConferenceEvent:  'AI Research Conference'  ← academic/professional conferences
      BusinessEvent:    'Westbrook Tech Summit'  ← trade shows, corporate events
      MusicEvent:       'The Velvet Circuit at The Blue Room'  ← concerts, gigs
      Hackathon:        'PDX Hackathon 2024'
      SocialEvent:      "Kenji's birthday dinner", 'farewell party'  ← informal gatherings
      EducationEvent:   'Machine Learning Workshop'  ← workshops, seminars, lectures
      ScreeningEvent:   'Tuesday night film screening'
      ExhibitionEvent:  'Annual Photography Exhibition'
      TheaterEvent:   'Hamlet at the Globe Theatre'  ← theater performances
      DanceEvent:     'Cascade Dance Company Spring Showcase'  ← dance performances
      PerformingArtsEvent: 'Portland Symphony Opening Night'  ← broader performing arts events
      LiteraryEvent:  'Portland Book Festival'  ← author readings, book launches
      FoodEvent:      'Portland Night Market'  ← food festivals, culinary events

    Products & Software:
      SoftwareApplication: 'NovaMind'
      Product:             'Ergonomic Pro X chair'  ← generic physical product
      Car:                 'Toyota Camry'  ← use Car for cars, Vehicle for others
      Drug:                'Metformin', 'ibuprofen'

    Medical:
      Conditions:
        MedicalCondition:    'Type 2 Diabetes', 'hypertension', 'asthma'
        InfectiousDisease:   'COVID-19', 'tuberculosis', 'influenza'  ← subclass of MedicalCondition
        MedicalSymptom:      'chest pain', 'shortness of breath'  ← observable symptom (subclass of MedicalCondition)
      Procedures — use the most specific subclass:
        SurgicalProcedure:       'appendectomy', 'knee replacement surgery', 'LASIK'
        DiagnosticProcedure:     'colonoscopy', 'biopsy', 'lumbar puncture'
        ImagingTest:             'MRI scan', 'CT scan', 'X-ray'  ← imaging-based test
        BloodTest:               'CBC', 'blood glucose test', 'HbA1c'  ← blood-based test
        PhysicalExam:            'cardiac stress test'  ← physical examination
        TherapeuticProcedure:    'chemotherapy', 'radiation therapy'  ← treatment procedures
        PhysicalTherapy:         'post-surgical rehabilitation'  ← subclass of TherapeuticProcedure
        PsychologicalTreatment:  'cognitive behavioral therapy', 'CBT'
      Devices:
        MedicalDevice:       'insulin pump', 'pacemaker', 'CPAP machine'
      Lifestyle & Wellness:
        PhysicalActivity:    'yoga', 'running', 'swimming'  ← exercise/sport as health activity
        Diet:                'Mediterranean diet', 'ketogenic diet'  ← named dietary regimen
        DietarySupplement:   'Vitamin D', 'omega-3 fatty acids'  ← supplements
        ExercisePlan:        "Dr. Nair's cardiac rehabilitation program"  ← structured exercise prescription
      Organizations (medical):
        MedicalClinic:       'Portland Urgent Care Clinic', 'Bright Smile Dental Clinic'
        DiagnosticLab:       'Quest Diagnostics', 'LabCorp'  ← pathology/lab services
        VeterinaryCare:      'Portland Animal Hospital'  ← veterinary clinics
      Research:
        MedicalStudy:        'Framingham Heart Study'  ← observational study
        MedicalTrial:        'Phase III trial of drug X'  ← clinical trial
        MedicalScholarlyArticle: '"Cardiac Outcomes in Type 2 Diabetes"'  ← medical academic paper
      Specialties & Tests:
        MedicalSpecialty:    'cardiology', 'neurology', 'oncology'  ← medical specializations
        MedicalTest:         'ECG', 'spirometry'  ← general/other diagnostic tests

    Intangible (non-physical, no more specific class):
      JobPosting:          'Senior Engineer at Helix Systems'  ← job listings
      Course:              'Introduction to Machine Learning'  ← named courses/programs
      Trip:                "Kenji's trip to Tokyo"  ← travel itineraries
      Language:            'Portuguese', 'Mandarin'
      Reservation:         'hotel booking at Grand Vista', 'restaurant reservation at Tanaka\'s Kitchen'
      Brand:               'NovaMind'  ← commercial brand (when distinct from the product/company)
      Occupation:          'cardiologist', 'documentary filmmaker'  ← professions when referenced as a named role

    SCHEMA.ORG GAPS — important notes:
    - 'Animal' is NOT a Schema.org class. For named pets, use 'Taxon' (the Schema.org
       class for biological organisms) or 'Thing' as a fallback.
    - 'Award' is NOT a Schema.org class. The property 'award' takes a Text value.
       Do NOT extract award names as standalone entity nodes; instead capture them
       via the 'award' relationship property on the winning Person/Organization/CreativeWork.
    - 'Podcast' is NOT a Schema.org class. Use 'PodcastSeries' for the show,
       'PodcastEpisode' for individual episodes.

    DO NOT EXTRACT:
    - Generic noun phrases ('the store', 'a hospital', 'some event', 'the platform')
    - Image captions or photo descriptions ('a woman in a garden', 'family photo')
    - Entities with more than 4 words in their name (likely image descriptions)
    - Pronouns or vague references ('he', 'she', 'someone', 'they')
    - Roles without a name ('a nurse', 'the CEO', 'a teacher')
    - Abstract concepts, adjectives, or feelings ('happiness', 'success', 'support')
    - Dates and time expressions (these are not entities)
    - Monetary amounts or prices ('$500', 'fifty dollars')

    Guidelines:
    - Use the most complete name form: 'Dr. Priya Nair' not 'Priya'
    - ALWAYS prefer the most specific subclass:
        'Hospital' not 'Organization', 'School' not 'EducationalOrganization',
        'Festival' not 'Event', 'Movie' not 'CreativeWork',
        'MusicRecording' not 'MusicAlbum' for a single song,
        'Hotel' not 'LodgingBusiness', 'Restaurant' not 'FoodEstablishment'
    - Use exact camelCase class names from the Schema.org reference
    - Only fall back to 'Organization', 'Place', 'CreativeWork', 'Event', or 'Thing'
      when no specific subclass fits
    """

    relevant_classes: str = dspy.InputField(
        desc="Schema.org classes most likely to appear in this text, retrieved via semantic "
             "similarity. Prioritize these when classifying entities. "
             "Format: ClassName(ParentClass) — description"
    )

    schema_reference: str = dspy.InputField(
        desc="Full Schema.org class and property reference. Use as fallback for any class "
             "not listed in relevant_classes. Use the exact class names listed here."
    )

    source_text: str = dspy.InputField(
        desc="The text to extract entities from"
    )

    extraction: EntityExtractionResult = dspy.OutputField(
        desc="All named entities with their most specific Schema.org class names. "
             "Only include proper nouns with at most 4 words in the name. "
             "Always prefer subclasses over parent classes."
    )
