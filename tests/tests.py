from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.test import TestCase

from bulk_sync import bulk_compare
from bulk_sync import bulk_sync
from .models import Company, Employee


class BulkSyncTests(TestCase):
    """ Test `bulk_sync` method """

    def setUp(self):
        pass

    def test_all_features_at_once(self):
        c1 = Company.objects.create(name="Foo Products, Ltd.")
        c2 = Company.objects.create(name="Bar Microcontrollers, Inc.")

        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        e2 = Employee.objects.create(name="Isaac", age=9, company=c1)
        e3 = Employee.objects.create(name="Zoe", age=9, company=c1)
        e4 = Employee.objects.create(name="Bob", age=25, company=c2)

        # We should update Scott's and Isaac's age, delete Zoe, add Newguy and
        # add a second Bob (since he's not in company c1, which we filtered on.)
        new_objs = [
            Employee(name="Scott", age=41, company=c1),
            Employee(name="Isaac", age=9, company=c1),
            Employee(name="Newguy", age=10, company=c1),
            Employee(name="Bob", age=50, company=c1),
        ]

        ret = bulk_sync(new_models=new_objs, filters=Q(company_id=c1.id), key_fields=("name",))

        self.assertEqual(2, ret["stats"]["updated"])
        self.assertEqual(2, ret["stats"]["created"])
        self.assertEqual(1, ret["stats"]["deleted"])

        self.assertEqual(4, Employee.objects.filter(company=c1).count())
        self.assertEqual(1, Employee.objects.filter(company=c2).count())

        new_e1 = Employee.objects.get(id=e1.id)
        self.assertEqual("Scott", new_e1.name)
        self.assertEqual(41, new_e1.age)
        self.assertEqual(c1, new_e1.company)

        new_e2 = Employee.objects.get(id=e2.id)
        self.assertEqual("Isaac", new_e2.name)
        self.assertEqual(9, new_e2.age)
        self.assertEqual(c1, new_e2.company)

        with self.assertRaises(Employee.DoesNotExist):
            Employee.objects.get(id=e3.id)

        new_e4 = Employee.objects.get(id=e4.id)
        self.assertEqual("Bob", new_e4.name)
        self.assertEqual(25, new_e4.age)
        self.assertEqual(c2, new_e4.company)

        new_e3 = Employee.objects.get(name="Newguy")
        self.assertEqual("Newguy", new_e3.name)
        self.assertEqual(10, new_e3.age)
        self.assertEqual(c1, new_e3.company)

        new_e5 = Employee.objects.get(name="Bob", company=c1)
        self.assertEqual("Bob", new_e5.name)
        self.assertEqual(50, new_e5.age)
        self.assertEqual(c1, new_e5.company)

    def test_provided_pk_is_retained_but_raises_if_mismatch_with_keyfield(self):
        c1 = Company.objects.create(name="Foo Products, Ltd.")
        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        new_objs = [Employee(id=e1.id, name="Notscott", age=41, company=c1)]

        with self.assertRaises(IntegrityError):
            # Crashes because e1.id already exists in database, even though 'name' doesnt match so it tries to INSERT.
            ret = bulk_sync(new_models=new_objs, filters=Q(company_id=c1.id), key_fields=("name",))

        unique_pk = Employee.objects.values_list('id', flat=True).order_by('-id').first() + 1
        new_objs = [Employee(id=unique_pk, name="Notscott", age=41, company=c1)]
        ret = bulk_sync(new_models=new_objs, filters=Q(company_id=c1.id), key_fields=("name",))

        self.assertEqual(0, ret["stats"]["updated"])
        self.assertEqual(1, ret["stats"]["created"]) # Added 'Notscott'
        self.assertEqual(1, ret["stats"]["deleted"]) # Deleted 'Scott'

        # Make sure we retained the PK
        self.assertEqual(Employee.objects.filter(id=unique_pk).count(), 1)


    def test_fields_parameter(self):
        c1 = Company.objects.create(name="Foo Products, Ltd.")
        c2 = Company.objects.create(name="Bar Microcontrollers, Inc.")

        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        e2 = Employee.objects.create(name="Isaac", age=9, company=c2)

        # We should update Scott's age, and not touch company.
        new_objs = [
            Employee(name="Scott", age=41, company=c1),
            Employee(name="Isaac", age=9, company=c1),
        ]

        ret = bulk_sync(new_models=new_objs, filters=None, key_fields=("name",), fields=['age'])

        new_e1 = Employee.objects.get(id=e1.id)
        self.assertEqual("Scott", new_e1.name)
        self.assertEqual(41, new_e1.age)
        self.assertEqual(c1, new_e1.company)

        new_e2 = Employee.objects.get(id=e2.id)
        self.assertEqual("Isaac", new_e2.name)
        self.assertEqual(9, new_e2.age)
        self.assertEqual(c2, new_e2.company)

        self.assertEqual(2, ret["stats"]["updated"])
        self.assertEqual(0, ret["stats"]["created"])
        self.assertEqual(0, ret["stats"]["deleted"])

    def test_skip_deletes(self):
        c1 = Company.objects.create(name="My Company LLC")

        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        e2 = Employee.objects.create(name="Isaac", age=9, company=c1)

        # update Scott - this makes Isaac is the "stale object" that would be deleted if skip_deletes were False
        new_objs = [
            Employee(name="Scott", age=41, company=c1),
        ]

        # but Isaac should remain when the skip_deletes flag is True
        ret = bulk_sync(new_models=new_objs, filters=None, key_fields=("name",), skip_deletes=True)

        self.assertEqual(["Scott", "Isaac"], [x.name for x in Employee.objects.all().order_by('id')])

        new_e1 = Employee.objects.get(id=e1.id)
        self.assertEqual(41, new_e1.age)

        self.assertEqual(2, Employee.objects.count())

        self.assertEqual(1, ret["stats"]["updated"])
        self.assertEqual(0, ret["stats"]["created"])
        self.assertEqual(0, ret["stats"]["deleted"])

    def test_skip_creates(self):
        c1 = Company.objects.create(name="My Company LLC")

        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        e2 = Employee.objects.create(name="Isaac", age=9, company=c1)

        # create a new employee that will be ignored
        new_objs = [
            Employee(name="John", age=52, company=c1)
        ]

        ret = bulk_sync(new_models=new_objs, filters=None, key_fields=("name",), skip_creates=True, skip_deletes=True)

        self.assertEqual(2, Employee.objects.count())
        self.assertEqual(["Scott", "Isaac"], [x.name for x in Employee.objects.all().order_by('id')])

        self.assertEqual(0, ret["stats"]["updated"])
        self.assertEqual(0, ret["stats"]["created"])
        self.assertEqual(0, ret["stats"]["deleted"])

    def test_skip_updates(self):
        c1 = Company.objects.create(name="My Company LLC")

        e1 = Employee.objects.create(name="Scott", age=40, company=c1)
        e2 = Employee.objects.create(name="Isaac", age=9, company=c1)

        # update employee that will be ignored, create a new one
        new_objs = [
            Employee(name="Scott", age=100, company=c1),
            Employee(name="Alice", age=36, company=c1)
        ]

        ret = bulk_sync(new_models=new_objs, filters=None, key_fields=("name",), skip_updates=True)

        # the age should not have been updated
        new_e1 = Employee.objects.get(id=e1.id)
        self.assertEqual(40, new_e1.age)

        # Isaac is "stale" object - was deleted, Alice was created
        self.assertEqual(2, Employee.objects.count())
        self.assertEqual(["Scott", "Alice"], [x.name for x in Employee.objects.all().order_by('id')])


        self.assertEqual(0, ret["stats"]["updated"])
        self.assertEqual(1, ret["stats"]["created"])
        self.assertEqual(1, ret["stats"]["deleted"])



class BulkCompareTests(TestCase):
    """ Test `bulk_compare` method """

    @classmethod
    def setUpTestData(cls):
        cls.c1 = Company.objects.create(name="Foo Products, Ltd.")
        cls.c2 = Company.objects.create(name="Bar Microcontrollers, Inc.")

        cls.e1 = Employee.objects.create(name="Scott", age=40, company=cls.c1)
        cls.e2 = Employee.objects.create(name="Isaac", age=9, company=cls.c1)
        cls.e3 = Employee.objects.create(name="Zoe", age=9, company=cls.c1)
        cls.e4 = Employee.objects.create(name="Bob", age=25, company=cls.c2)

        # We should update Scott's and Isaac's age, delete Zoe, add Newguy and
        # add a second Bob (since he's not in company c1, which we filtered on.)
        cls.new_objs = [
            Employee(name="Scott", age=41, company=cls.c1),
            Employee(name="Isaac", age=9, company=cls.c1),
            Employee(name="Newguy", age=10, company=cls.c1),
            Employee(name="Bob", age=50, company=cls.c1),
        ]

    def test_bulk_compare(self):
        c1 = self.c1
        e3 = self.e3
        new_objs = self.new_objs

        ret = bulk_compare(old_models=Employee.objects.filter(company=c1), new_models=new_objs, key_fields=("name",))

        self.assertEqual([new_objs[2], new_objs[3]], ret["added"])
        self.assertEqual([e3], list(ret["removed"]))
        self.assertEqual([new_objs[0]], ret["updated"])
        self.assertEqual({new_objs[0]: {"age": (40, 41)}}, ret["updated_details"])
        self.assertEqual([new_objs[1]], ret["unchanged"])

    def test_bulk_compare_with_ignore_int_field(self):
        c1 = self.c1
        e3 = self.e3
        new_objs = self.new_objs

        ret = bulk_compare(
            old_models=Employee.objects.filter(company=c1).order_by("name"),
            new_models=new_objs,
            key_fields=("name",),
            ignore_fields=("age",),
        )

        self.assertEqual([new_objs[2], new_objs[3]], ret["added"])
        self.assertEqual([e3], list(ret["removed"]))
        self.assertEqual([], ret["updated"])
        self.assertEqual({}, ret["updated_details"])
        self.assertEqual([new_objs[0], new_objs[1]], ret["unchanged"])

    def test_bulk_compare_with_ignore_relation_field(self):
        c1 = self.c1
        e3 = self.e3
        new_objs = self.new_objs

        ret = bulk_compare(
            old_models=Employee.objects.filter(company=c1).order_by("name"),
            new_models=new_objs,
            key_fields=("name",),
            ignore_fields=("company_id",),
        )

        self.assertEqual([new_objs[2], new_objs[3]], ret["added"])
        self.assertEqual([e3], list(ret["removed"]))
        self.assertEqual([new_objs[0]], ret["updated"])
        self.assertEqual({new_objs[0]: {'age': (40, 41)}}, ret["updated_details"])
        self.assertEqual([new_objs[1]], ret["unchanged"])
